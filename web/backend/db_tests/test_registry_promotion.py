"""Atomic promotion over real PostgreSQL and durable isolated artifact storage."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from threading import Barrier

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scripts.artifact_store import FilesystemArtifactStore, InvalidArtifact
from scripts.registry import canonical_json
from scripts.reviewed_candidate import CandidateApprovalError, ReviewedCandidate, candidate_digest
from web.backend.app.api.registry_compatibility import V1RepresentabilityError
from web.backend.app.db.models import (
    Artifact,
    BuildProvenance,
    ModuleChannel,
    ModuleVersion,
    PromotionEvent,
)
from web.backend.app.db.repository import RegistryConflict
from web.backend.app.main import create_app
from web.backend.app.registry_import_v1 import import_registry
from web.backend.app.registry_promotion import PromotionIntent, RegistryPromotionService
from web.backend.db_tests.conftest import ROOT, migration_config
from web.backend.db_tests.test_registry_database import snapshot


class Evidence:
    """Test-only source adapter; production always verifies GitHub main/merged PR."""

    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def load(self, module_id, version, approval_pr, expected):
        if (self.value["module_id"], self.value["version"], candidate_digest(self.value)) != (
            module_id,
            version,
            expected,
        ):
            raise CandidateApprovalError("Candidate mismatch")
        return ReviewedCandidate(
            canonical_json(self.value),
            expected,
            f"https://github.com/oklabflensburg/open-city-planner-packages/pull/{approval_pr}",
            "human-reviewer",
            "a" * 40,
        )


@pytest.fixture
def promotion(pg_engine, tmp_path):
    import_registry(pg_engine, ROOT / "registry")
    candidate = json.loads((ROOT / "candidates/statistics/0.4.0/provenance.json").read_text())
    # Hermetic synthetic bytes for failure/concurrency tests, never represented as real pilot.
    artifact = tmp_path / "fixture.ocp"
    artifact.write_bytes(b"synthetic reviewed promotion test bytes")
    candidate["bundle_sha256"] = sha256(artifact.read_bytes()).hexdigest()
    source = Evidence(candidate)
    intent = PromotionIntent(
        "statistics",
        "0.4.0",
        41,
        candidate_digest(candidate),
        candidate["bundle_sha256"],
        "stable",
        1,
        "approved-intent-1",
    )
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    service = RegistryPromotionService(pg_engine, store, candidate_source=source)
    return service, intent, artifact, source


def test_atomic_publication_immediate_visibility_and_persistent_retry(promotion, pg_engine):
    service, intent, artifact, _ = promotion
    with TestClient(
        create_app(v2_enabled=True, v1_compat_enabled=True, engine_factory=lambda: pg_engine)
    ) as client:
        old_etag = client.get("/index.json").headers["etag"]
        assert client.get("/api/v1/modules/statistics").json()["stable_version"] == "0.3.0"
        result = service.promote(intent, artifact)
        assert result["status"] == "published"
        assert result["previous_channel_target"] == "0.3.0"
        assert result["new_channel_target"] == "0.4.0"
        assert result["channel_revision"] == 2
        assert client.get("/api/v1/modules/statistics").json()["stable_version"] == "0.4.0"
        assert client.get("/api/v1/modules/statistics/versions/0.4.0").status_code == 200
        index = client.get("/index.json", headers={"If-None-Match": old_etag})
        assert index.status_code == 200 and index.headers["etag"] != old_etag
        assert (
            next(m for m in index.json()["modules"] if m["id"] == "statistics")["channels"][
                "stable"
            ]["version"]
            == "0.4.0"
        )
        versions = client.get("/modules/statistics.json").json()["versions"]
        assert [v["version"] for v in versions] == ["0.2.0", "0.3.0", "0.4.0"]
        assert versions[-1]["artifact"]["sha256"] == intent.bundle_sha256
        assert versions[-1]["channel"] == "stable"
        before = snapshot(pg_engine)
        # A fresh service has no process-local idempotency state.
        restarted = RegistryPromotionService(
            pg_engine, service.store, candidate_source=service.candidate_source
        )
        assert restarted.promote(intent, artifact) == {**result, "status": "already-published"}
        assert snapshot(pg_engine) == before
    with Session(pg_engine) as session:
        version = session.get(ModuleVersion, ("statistics", "0.4.0"))
        assert version.published_at is not None
        provenance = session.get(BuildProvenance, version.build_provenance_id)
        assert provenance.builder_version == "1"
        assert provenance.builder_commit == "e406fb2267e7e28eaba2f7e8384a876e9e10a2f8"
        assert provenance.reproducible is True
        assert provenance.host_contract_status == "passed"
        assert provenance.host_commit is None and provenance.environment_json is None
        stored = session.get(Artifact, version.artifact_id)
        assert stored.byte_size == artifact.stat().st_size
        assert stored.storage_locator == result["storage_locator"]
        assert (
            session.get(PromotionEvent, intent.idempotency_key).candidate_digest
            == intent.candidate_sha256
        )


@pytest.mark.parametrize("kind", ["missing", "digest", "unreviewed", "candidate", "channel"])
def test_evidence_and_artifact_fail_before_db(promotion, pg_engine, monkeypatch, kind):
    service, intent, artifact, source = promotion
    before = snapshot(pg_engine)
    if kind == "missing":
        artifact.unlink()
    elif kind == "digest":
        artifact.write_bytes(b"wrong")
    elif kind == "unreviewed":

        def reject(*args):
            raise CandidateApprovalError("Unreviewed")

        monkeypatch.setattr(source, "load", reject)
    elif kind == "candidate":
        source.value["source_commit"] = "f" * 40
    else:
        intent = replace(intent, channel="beta")

    def no_connect(*args, **kwargs):
        pytest.fail("DB must not be accessed before evidence and stored bytes are verified")

    with monkeypatch.context() as patch:
        patch.setattr(pg_engine, "connect", no_connect)
        with pytest.raises((CandidateApprovalError, RegistryConflict, InvalidArtifact)):
            service.promote(intent, artifact)
    assert snapshot(pg_engine) == before


@pytest.mark.parametrize("kind", ["dependency", "specifier", "representability", "audit"])
def test_full_rollback_keeps_valid_orphan(promotion, pg_engine, monkeypatch, kind):
    service, intent, artifact, source = promotion
    if kind == "dependency":
        source.value["requires"]["modules"] = {"not-registered": ">=1.0.0"}
    elif kind == "specifier":
        source.value["requires"]["host"] = "nonsense"
    elif kind == "representability":
        with pg_engine.begin() as connection:
            connection.execute(
                update(ModuleChannel)
                .where(ModuleChannel.module_id == "analysis-areas")
                .values(version="1.0.0")
            )
    else:
        from sqlalchemy import event

        def reject_audit(_mapper, _connection, _target):
            raise RegistryConflict("Injected audit insert failure")

        event.listen(PromotionEvent, "before_insert", reject_audit)
    intent = replace(intent, candidate_sha256=candidate_digest(source.value))
    before = snapshot(pg_engine)
    try:
        with pytest.raises((ValueError, V1RepresentabilityError)):
            service.promote(intent, artifact)
        assert snapshot(pg_engine) == before
        assert (
            service.store.verify("statistics", "0.4.0", intent.bundle_sha256).digest
            == intent.bundle_sha256
        )
    finally:
        if kind == "audit":
            event.remove(PromotionEvent, "before_insert", reject_audit)


def test_db_outage_after_durable_publish(promotion, pg_engine, monkeypatch):
    service, intent, artifact, _ = promotion
    before = snapshot(pg_engine)

    def offline(*args, **kwargs):
        raise OperationalError("private", {}, Exception("secret"))

    with monkeypatch.context() as patch:
        patch.setattr(pg_engine, "connect", offline)
        with pytest.raises(OperationalError):
            service.promote(intent, artifact)
    assert service.store.exists("statistics", "0.4.0")
    assert snapshot(pg_engine) == before
    assert service.promote(intent, artifact)["status"] == "published"


@pytest.mark.parametrize(
    "field",
    [
        "source_commit",
        "requires",
        "bundle_format_version",
        "source_tag",
        "builder_commit",
        "planned_channel",
    ],
)
def test_conflicting_retry_never_mutates(promotion, pg_engine, field):
    service, intent, artifact, source = promotion
    service.promote(intent, artifact)
    before = snapshot(pg_engine)
    replacements = {
        "requires": {"host": ">=0.3.0", "sdk": ">=1.15.0", "modules": {}},
        "bundle_format_version": 2,
        "planned_channel": "beta",
        "source_tag": "other",
    }
    source.value[field] = replacements.get(field, "f" * 40)
    intent = replace(
        intent,
        candidate_sha256=candidate_digest(source.value),
        channel=source.value["planned_channel"],
    )
    with pytest.raises(ValueError):
        service.promote(intent, artifact)
    assert snapshot(pg_engine) == before


def test_different_key_same_version_conflicts(promotion, pg_engine):
    service, intent, artifact, _ = promotion
    service.promote(intent, artifact)
    before = snapshot(pg_engine)
    with pytest.raises(RegistryConflict, match="another promotion intent"):
        service.promote(replace(intent, idempotency_key="new-key"), artifact)
    assert snapshot(pg_engine) == before


def test_concurrent_same_intent_one_event(promotion, pg_engine):
    service, intent, artifact, _ = promotion
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=10)
        return service.promote(intent, artifact)["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        assert sorted(f.result(timeout=20) for f in futures) == ["already-published", "published"]
    with Session(pg_engine) as session:
        assert len(session.scalars(select(PromotionEvent)).all()) == 1
        assert session.get(ModuleChannel, ("statistics", "stable")).revision == 2


def test_concurrent_different_intents_stale_revision(promotion, pg_engine):
    service, intent, artifact, source = promotion
    other = copy.deepcopy(source.value)
    other.update(version="0.5.0", source_tag="v0.5.0")
    other_service = RegistryPromotionService(
        pg_engine, service.store, candidate_source=Evidence(other)
    )
    other_intent = replace(
        intent,
        version="0.5.0",
        idempotency_key="other-intent",
        candidate_sha256=candidate_digest(other),
    )
    barrier = Barrier(2)

    def run(promoter, plan):
        barrier.wait(timeout=10)
        try:
            return promoter.promote(plan, artifact)["status"]
        except RegistryConflict as exc:
            assert "Stale channel revision" in str(exc)
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, service, intent), pool.submit(run, other_service, other_intent)]
        assert sorted(f.result(timeout=20) for f in futures) == ["published", "stale"]
    with Session(pg_engine) as session:
        assert len(session.scalars(select(PromotionEvent)).all()) == 1
        assert session.get(ModuleChannel, ("statistics", "stable")).revision == 2


def test_committed_audit_cannot_be_downgraded(promotion, pg_engine):
    service, intent, artifact, _ = promotion
    service.promote(intent, artifact)
    with pg_engine.begin() as connection:
        with pytest.raises(RuntimeError, match="Cannot discard"):
            command.downgrade(migration_config(connection), "0045_registry_v2")
        assert connection.scalar(text("SELECT count(*) FROM promotion_events")) == 1


def test_retry_after_later_promotion_does_not_rewind_channel(promotion, pg_engine):
    service, intent, artifact, source = promotion
    first = service.promote(intent, artifact)
    next_value = copy.deepcopy(source.value)
    next_value.update(version="0.5.0", source_tag="v0.5.0")
    promoter = RegistryPromotionService(
        pg_engine, service.store, candidate_source=Evidence(next_value)
    )
    next_intent = replace(
        intent,
        version="0.5.0",
        expected_channel_revision=2,
        candidate_sha256=candidate_digest(next_value),
        idempotency_key="next",
    )
    # Different versions need different digest identities for distinct canonical storage bindings.
    other_artifact = artifact.with_name("other.ocp")
    other_artifact.write_bytes(b"next reviewed bytes")
    next_value["bundle_sha256"] = sha256(other_artifact.read_bytes()).hexdigest()
    promoter.candidate_source = Evidence(next_value)
    next_intent = replace(
        next_intent,
        bundle_sha256=next_value["bundle_sha256"],
        candidate_sha256=candidate_digest(next_value),
    )
    promoter.promote(next_intent, other_artifact)
    before = snapshot(pg_engine)
    assert service.promote(intent, artifact) == {**first, "status": "already-published"}
    assert snapshot(pg_engine) == before
    with Session(pg_engine) as session:
        assert session.get(ModuleChannel, ("statistics", "stable")).version == "0.5.0"


def test_same_key_other_digest_is_hard_conflict(promotion, pg_engine):
    from scripts.artifact_store import ArtifactConflict

    service, intent, artifact, source = promotion
    service.promote(intent, artifact)
    before = snapshot(pg_engine)
    artifact.write_bytes(b"changed bytes")
    source.value["bundle_sha256"] = sha256(artifact.read_bytes()).hexdigest()
    changed = replace(
        intent,
        bundle_sha256=source.value["bundle_sha256"],
        candidate_sha256=candidate_digest(source.value),
    )
    with pytest.raises(ArtifactConflict):
        service.promote(changed, artifact)
    assert snapshot(pg_engine) == before


def test_promotion_cannot_move_stable_below_historical_maximum(promotion, pg_engine):
    service, intent, artifact, source = promotion
    source.value.update(version="0.1.0", source_tag="v0.1.0")
    intent = replace(intent, version="0.1.0", candidate_sha256=candidate_digest(source.value))
    before = snapshot(pg_engine)
    with pytest.raises(V1RepresentabilityError):
        service.promote(intent, artifact)
    assert snapshot(pg_engine) == before
    assert service.store.exists("statistics", "0.1.0")


def test_existing_immutable_version_without_event_conflicts(promotion, pg_engine):
    from web.backend.app.db.repository import RegistryDatabaseRepository

    service, intent, artifact, _ = promotion
    with Session(pg_engine) as session, session.begin():
        repo = RegistryDatabaseRepository(session)
        release = copy.deepcopy(repo.project_v1("statistics")[0]["versions"][-1])
        release.update(version="0.4.0", source_tag="v0.4.0")
        release["artifact"] = {
            "url": service.store.public_url("statistics", "0.4.0"),
            "sha256": intent.bundle_sha256,
        }
        repo.insert_published_version("statistics", release)
    before = snapshot(pg_engine)
    with pytest.raises(RegistryConflict, match="Immutable version conflict"):
        service.promote(intent, artifact)
    assert snapshot(pg_engine) == before


def test_production_cli_requires_explicit_gate_before_any_external_access(tmp_path):
    import os
    import subprocess
    import sys

    args = [
        sys.executable,
        "-m",
        "web.backend.app.registry_promote",
        "--module",
        "statistics",
        "--version",
        "0.4.0",
        "--channel",
        "stable",
        "--approval-pr",
        "41",
        "--candidate-sha256",
        "70be3863818e41678fe7c7adeef69edbf865a18d7494a50021cf52e043239626",
        "--bundle-sha256",
        "f" * 64,
        "--expected-channel-revision",
        "1",
        "--idempotency-key",
        "test",
        "--artifact-root",
        str(tmp_path),
        "--artifact",
        str(tmp_path / "absent.ocp"),
        "--mode",
        "production",
    ]
    for flags in ([], ["--confirm-production-promotion"]):
        result = subprocess.run(
            args + flags,
            capture_output=True,
            text=True,
            env={**os.environ, "PACKAGES_REGISTRY_WRITER_CUTOVER_ENABLED": "false"},
        )
        assert result.returncode == 2
        assert "Production requires explicit confirmation" in result.stderr
