from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from scripts import publish_artifacts, verify_artifacts
from scripts.publish_artifacts import (
    ArtifactPublishingError,
    canonical_artifact_relative_path,
    publish_candidate,
    select_release,
)
from scripts.registry import RegistryValidationError
from scripts.verify_artifacts import ArtifactVerificationError, ReleaseCandidate

PAYLOAD = b"analysis-areas immutable artifact bytes"
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()
SOURCE_URL = (
    "https://github.com/oklabflensburg/ocp-module-analysis-areas/releases/download/"
    "v1.0.0/analysis-areas-1.0.0.ocp"
)


def candidate(expected_sha256: str = PAYLOAD_SHA256) -> ReleaseCandidate:
    return ReleaseCandidate(
        module_id="analysis-areas",
        version="1.0.0",
        channel="stable",
        artifact_url=SOURCE_URL,
        expected_sha256=expected_sha256,
        classification="first-party",
    )


def successful_download(observed_target: Path | None = None):
    def download(release, destination, timeout, max_bytes):
        if observed_target is not None:
            assert not observed_target.exists()
        assert destination.name.startswith(".analysis-areas-1.0.0.ocp.")
        assert destination.name.endswith(".partial")
        destination.write_bytes(PAYLOAD)
        return hashlib.sha256(PAYLOAD).hexdigest()

    return download


def test_selects_published_analysis_areas_release() -> None:
    repository = Path(__file__).parents[1]
    release = select_release(repository / "registry", "analysis-areas", "1.0.0")
    assert release.artifact_url == SOURCE_URL
    assert release.expected_sha256 == (
        "7006f31ea73f40e38f63d2065652c27ad5d3391ddcc8cfad2f149993efef3dcf"
    )


def test_new_artifact_is_published_atomically(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    target = root / canonical_artifact_relative_path("analysis-areas", "1.0.0")
    verifier_calls = []

    def verifier(release, artifact, host_root, state_root):
        assert not target.exists()
        assert artifact.name.endswith(".verify.ocp")
        assert artifact.read_bytes() == PAYLOAD
        verifier_calls.append((release.identity, host_root, state_root))

    result = publish_candidate(
        candidate(),
        root,
        host_verifier_root=tmp_path / "host",
        downloader=successful_download(target),
        verifier=verifier,
        validate_checkout=lambda host_root: None,
    )

    assert result.status == "published"
    assert result.target_path == target
    assert target.read_bytes() == PAYLOAD
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert verifier_calls and verifier_calls[0][0] == "analysis-areas@1.0.0"
    assert not list(target.parent.glob(".*.partial"))
    assert not list(target.parent.glob(".*.verify.ocp"))


def test_same_digest_is_idempotent_without_download(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    first = publish_candidate(candidate(), root, downloader=successful_download())

    def unexpected_download(*args, **kwargs):
        raise AssertionError("idempotent publication must not download again")

    second = publish_candidate(candidate(), root, downloader=unexpected_download)
    assert first.status == "published"
    assert second.status == "already-present"
    assert second.target_path.read_bytes() == PAYLOAD


def test_existing_different_digest_fails_without_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    target = root / canonical_artifact_relative_path("analysis-areas", "1.0.0")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing different bytes")

    with pytest.raises(ArtifactPublishingError, match="refusing overwrite"):
        publish_candidate(
            candidate(),
            root,
            downloader=lambda *args, **kwargs: pytest.fail("download must not start"),
        )
    assert target.read_bytes() == b"existing different bytes"


def test_downloaded_sha_mismatch_never_publishes_and_cleans_partial(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"

    def mismatched_download(release, destination, timeout, max_bytes):
        destination.write_bytes(b"wrong bytes")
        return hashlib.sha256(b"wrong bytes").hexdigest()

    with pytest.raises(ArtifactPublishingError, match="downloaded SHA-256"):
        publish_candidate(candidate(), root, downloader=mismatched_download)
    target = root / canonical_artifact_relative_path("analysis-areas", "1.0.0")
    assert not target.exists()
    assert not list(target.parent.glob(".*.partial"))


def test_host_verifier_failure_never_publishes(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"

    def failed_verifier(release, artifact, host_root, state_root):
        raise ArtifactVerificationError("host verifier rejected artifact")

    with pytest.raises(ArtifactPublishingError, match="host verifier rejected"):
        publish_candidate(
            candidate(),
            root,
            host_verifier_root=tmp_path / "host",
            downloader=successful_download(),
            verifier=failed_verifier,
            validate_checkout=lambda host_root: None,
        )
    target = root / canonical_artifact_relative_path("analysis-areas", "1.0.0")
    assert not target.exists()
    assert not list(target.parent.glob(".*.partial"))
    assert not list(target.parent.glob(".*.verify.ocp"))


def test_atomic_no_clobber_wins_publication_race(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    target = root / canonical_artifact_relative_path("analysis-areas", "1.0.0")

    def racing_verifier(release, artifact, host_root, state_root):
        target.write_bytes(b"concurrent publisher bytes")

    with pytest.raises(ArtifactPublishingError, match="refusing overwrite"):
        publish_candidate(
            candidate(),
            root,
            host_verifier_root=tmp_path / "host",
            downloader=successful_download(target),
            verifier=racing_verifier,
            validate_checkout=lambda host_root: None,
        )
    assert target.read_bytes() == b"concurrent publisher bytes"
    assert not list(target.parent.glob(".*.partial"))
    assert not list(target.parent.glob(".*.verify.ocp"))


@pytest.mark.parametrize(
    ("module_id", "version"),
    [
        ("../analysis-areas", "1.0.0"),
        ("analysis/areas", "1.0.0"),
        ("analysis-areas", "../1.0.0"),
        ("analysis-areas", "v1.0.0"),
        ("analysis-areas", "%2e%2e"),
    ],
)
def test_canonical_target_rejects_path_traversal(module_id: str, version: str) -> None:
    with pytest.raises(RegistryValidationError):
        canonical_artifact_relative_path(module_id, version)


def test_publisher_reuses_the_artifact_gate_security_helpers() -> None:
    assert publish_artifacts.download_artifact is verify_artifacts.download_artifact
    assert publish_artifacts.run_host_verifier is verify_artifacts.run_host_verifier
    assert publish_artifacts.validate_candidate_url is verify_artifacts.validate_candidate_url


def test_registry_source_with_forbidden_url_fails_before_downloader(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    modules = registry / "modules"
    modules.mkdir(parents=True)
    (registry / "registry.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    metadata = json.loads(
        (Path(__file__).parents[1] / "registry/modules/analysis-areas.json").read_text(
            encoding="utf-8"
        )
    )
    metadata["versions"][0]["artifact"]["url"] = "https://example.invalid/artifact.ocp"
    (modules / "analysis-areas.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(RegistryValidationError, match="hosting policy"):
        select_release(registry, "analysis-areas", "1.0.0")
