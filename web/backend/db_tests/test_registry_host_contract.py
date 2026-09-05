"""Pinned real Host consumer contract, required when configured (always in DB CI)."""

import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.verify_artifacts import validate_host_verifier_checkout
from web.backend.app.main import create_app
from web.backend.app.registry_import_v1 import import_registry
from web.backend.db_tests.conftest import ROOT


@pytest.fixture
def host():
    value = os.environ.get("PACKAGES_REGISTRY_HOST_VERIFIER_ROOT")
    if not value:
        pytest.skip("Set PACKAGES_REGISTRY_HOST_VERIFIER_ROOT for the pinned real Host contract")
    root = Path(value).resolve()
    validate_host_verifier_checkout(root)
    return root


def run_host(host, mode, root):
    result = subprocess.run(
        [
            str(host / "backend/.venv/bin/python"),
            str(ROOT / "web/backend/db_tests/host_contract/verify_snapshot.py"),
            mode,
            str(root),
        ],
        cwd=host / "backend",
        env={**os.environ, "PYTHONPATH": str(host / "backend")},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def capture_snapshot(engine, root):
    with TestClient(
        create_app(v2_enabled=False, v1_compat_enabled=True, engine_factory=lambda: engine)
    ) as client:
        response = client.get("/index.json")
        assert response.status_code == 200
        snapshot = root / "snapshot"
        (snapshot / "modules").mkdir(parents=True)
        (snapshot / "index.json").write_bytes(response.content)
        for entry in response.json()["modules"]:
            metadata = client.get(entry["metadata"])
            assert metadata.status_code == 200
            (snapshot / entry["metadata"].lstrip("/")).write_bytes(metadata.content)


def test_current_db_http_output_with_pinned_host(pg_engine, host, tmp_path):
    import_registry(pg_engine, ROOT / "registry")
    capture_snapshot(pg_engine, tmp_path)
    run_host(host, "verify", tmp_path)


def test_db_http_output_to_real_bundle_installer(pg_engine, host, tmp_path):
    run_host(host, "prepare", tmp_path)
    import_registry(pg_engine, tmp_path / "source")
    capture_snapshot(pg_engine, tmp_path)
    run_host(host, "install", tmp_path)


def test_dependency_metadata_roundtrip_with_real_host(pg_engine, host, tmp_path):
    from sqlalchemy.orm import Session

    from web.backend.app.db.models import ModuleDependency

    import_registry(pg_engine, ROOT / "registry")
    with Session(pg_engine) as session, session.begin():
        # Synthetic dependency metadata in a disposable schema; history in Git is untouched.
        session.add(
            ModuleDependency(
                owner_module_id="statistics",
                owner_version="0.3.0",
                dependency_module_id="search",
                specifier=">=0.1.0,<1.0.0",
            )
        )
    capture_snapshot(pg_engine, tmp_path)
    run_host(host, "verify", tmp_path)


def test_reviewed_statistics_promotion_with_original_bytes(pg_engine, host, tmp_path):
    import json
    import shutil

    from scripts.artifact_store import FilesystemArtifactStore
    from scripts.reviewed_candidate import GitHubCandidateSource, extract_reviewed_archive
    from web.backend.app.registry_promotion import PromotionIntent, RegistryPromotionService

    fixture = ROOT / "tests/fixtures/reviewed-statistics-0.4.0"
    evidence = json.loads((fixture / "github-evidence.json").read_text())
    reviewer = GitHubCandidateSource(evidence.__getitem__)  # recorded public GitHub, no CI network
    digest = "70be3863818e41678fe7c7adeef69edbf865a18d7494a50021cf52e043239626"
    reviewed = reviewer.load("statistics", "0.4.0", 41, digest)
    artifact = extract_reviewed_archive(fixture / "candidate.zip", reviewed, tmp_path / "input")
    import_registry(pg_engine, ROOT / "registry")
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    service = RegistryPromotionService(pg_engine, store, candidate_source=reviewer)
    intent = PromotionIntent(
        "statistics",
        "0.4.0",
        41,
        digest,
        reviewed.value["bundle_sha256"],
        "stable",
        1,
        "statistics-real-pilot",
    )
    with TestClient(
        create_app(v2_enabled=True, v1_compat_enabled=True, engine_factory=lambda: pg_engine)
    ) as client:
        assert client.get("/api/v1/modules/statistics").json()["stable_version"] == "0.3.0"
        result = service.promote(intent, artifact)
        assert result["status"] == "published"
        assert client.get("/api/v1/modules/statistics").json()["stable_version"] == "0.4.0"
        assert client.get("/api/v1/modules/statistics/versions/0.4.0").status_code == 200
        snapshot = tmp_path / "snapshot"
        (snapshot / "modules").mkdir(parents=True)
        index = client.get("/index.json")
        (snapshot / "index.json").write_bytes(index.content)
        for entry in index.json()["modules"]:
            metadata = client.get(entry["metadata"])
            assert metadata.status_code == 200
            (snapshot / entry["metadata"].lstrip("/")).write_bytes(metadata.content)
        stored = store.root / result["storage_locator"]
        shutil.copyfile(stored, tmp_path / "statistics-0.4.0.ocp")
        run_host(host, "statistics-pilot", tmp_path)
