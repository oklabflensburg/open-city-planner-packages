"""Trusted internal promotion: reviewed evidence → durable bytes → one DB commit."""

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from scripts.artifact_store import ArtifactStore
from scripts.registry import canonical_json, validate_module
from scripts.registry_candidate import candidate_release
from scripts.reviewed_candidate import GitHubCandidateSource, candidate_digest
from web.backend.app.api.registry_compatibility import validate_v1_representability
from web.backend.app.api.registry_v2 import EXPECTED_SCHEMA_REVISION
from web.backend.app.db.models import Artifact, Module, ModuleChannel, PromotionEvent
from web.backend.app.db.repository import RegistryConflict, RegistryDatabaseRepository


@dataclass(frozen=True)
class PromotionIntent:
    module_id: str
    version: str
    approval_pr: int
    candidate_sha256: str
    bundle_sha256: str
    channel: str
    expected_channel_revision: int
    idempotency_key: str


class RegistryPromotionService:
    def __init__(self, engine, store: ArtifactStore, *, candidate_source=None):
        self.engine = engine
        self.store = store
        self.candidate_source = candidate_source or GitHubCandidateSource()

    def promote(self, intent: PromotionIntent, source: Path):
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,199}", intent.idempotency_key)
            or type(intent.expected_channel_revision) is not int
            or intent.expected_channel_revision < 0
        ):
            raise RegistryConflict("Invalid promotion key or expected channel revision")
        reviewed = self.candidate_source.load(
            intent.module_id, intent.version, intent.approval_pr, intent.candidate_sha256
        )
        value = reviewed.value
        if (
            candidate_digest(value) != intent.candidate_sha256
            or value["planned_channel"] != intent.channel
            or value["bundle_sha256"] != intent.bundle_sha256
        ):
            raise RegistryConflict("Intent does not match reviewed candidate")
        release = candidate_release(value)
        environment = value.get("build_environment")
        provenance = {
            "source_repository": value["source_repository"],
            "source_tag": value["source_tag"],
            "source_commit": value["source_commit"],
            "builder_version": str(value["builder_version"]),
            "builder_commit": value["builder_commit"],
            "host_commit": environment.get("host_commit") if environment else None,
            "reproducible": True,
            "host_contract_status": "passed",
            "environment_json": environment,
        }
        bound_intent = {
            **intent.__dict__,
            "approval_reference": reviewed.approval_reference,
            "approval_identity": reviewed.approval_identity,
            "merge_commit": reviewed.merge_commit,
            "candidate": value,
        }
        # The storage implementation verifies source, fsyncs and verifies final bytes.
        # No connection/DB transaction may precede durable publication.
        self.store.publish(intent.module_id, intent.version, source, intent.bundle_sha256)
        artifact = self.store.verify(intent.module_id, intent.version, intent.bundle_sha256)
        if (
            artifact.digest != intent.bundle_sha256
            or artifact.public_url != release["artifact"]["url"]
        ):
            raise RegistryConflict("Stored artifact differs from approved binding")
        with Session(self.engine) as session, session.begin():
            # Also serialize global key reuse across different modules. All writers take
            # locks in this order: key, then module; hash collisions only serialize more.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 49))"),
                {"key": intent.idempotency_key},
            )
            repo = RegistryDatabaseRepository(session)
            if repo.schema_revision() != EXPECTED_SCHEMA_REVISION:
                raise RegistryConflict("Registry schema is not ready for promotion")
            module = session.scalar(
                select(Module).where(Module.id == intent.module_id).with_for_update()
            )
            if module is None or module.source_repository != value["source_repository"]:
                raise RegistryConflict("Candidate does not match registered module identity")
            if module.classification != value["classification"]:
                raise RegistryConflict("Candidate classification differs from registered module")
            validate_module({**repo.module_structure(module), "versions": [release]}, "promotion")
            previous_event = session.get(PromotionEvent, intent.idempotency_key)
            if previous_event is not None:
                if canonical_json(previous_event.intent) != canonical_json(bound_intent):
                    raise RegistryConflict("Idempotency key conflicts with committed intent")
                # Validate immutable metadata too, but never rewind a later channel update.
                repo.insert_published_version(
                    intent.module_id, release, provenance_values=provenance
                )
                return {**previous_event.result, "status": "already-published"}
            if (
                session.scalar(
                    select(PromotionEvent).where(
                        PromotionEvent.module_id == intent.module_id,
                        PromotionEvent.version == intent.version,
                    )
                )
                is not None
            ):
                raise RegistryConflict("Version already belongs to another promotion intent")
            channel = session.get(ModuleChannel, (intent.module_id, intent.channel))
            revision = channel.revision if channel else 0
            if revision != intent.expected_channel_revision:
                raise RegistryConflict("Stale channel revision; fresh approval required")
            previous = channel.version if channel else None
            stored = repo.ensure_record(
                Artifact, {"digest_algorithm": "sha256", "digest": artifact.digest}
            )
            # Complete unknown imported storage metadata, never replace known evidence.
            for field in ("byte_size", "storage_locator"):
                expected = getattr(artifact, field)
                if getattr(stored, field) not in (None, expected):
                    raise RegistryConflict("Existing artifact storage binding conflicts")
                setattr(stored, field, expected)
            if not repo.insert_published_version(
                intent.module_id, release, provenance_values=provenance
            ):
                raise RegistryConflict(
                    "Existing version has no matching committed promotion intent"
                )
            if channel is None:
                session.add(
                    ModuleChannel(
                        module_id=intent.module_id,
                        channel=intent.channel,
                        version=intent.version,
                        revision=1,
                    )
                )
            else:
                channel.version, channel.revision = intent.version, revision + 1
            session.flush()
            # Entire future state remains invisible; any guard failure rolls it ALL back.
            validate_v1_representability(repo.project_v1(), repo.channel_targets())
            result = {
                "promotion_id": intent.idempotency_key,
                "module": intent.module_id,
                "version": intent.version,
                "channel": intent.channel,
                "previous_channel_target": previous,
                "new_channel_target": intent.version,
                "channel_revision": revision + 1,
                "artifact_sha256": artifact.digest,
                "artifact_url": artifact.public_url,
                "storage_locator": artifact.storage_locator,
                "byte_size": artifact.byte_size,
                "status": "published",
            }
            session.add(
                PromotionEvent(
                    idempotency_key=intent.idempotency_key,
                    module_id=intent.module_id,
                    version=intent.version,
                    channel=intent.channel,
                    candidate_digest=intent.candidate_sha256,
                    approval_reference=reviewed.approval_reference,
                    approval_identity=reviewed.approval_identity,
                    previous_channel_version=previous,
                    new_channel_version=intent.version,
                    intent=bound_intent,
                    result=result,
                )
            )
        return result
