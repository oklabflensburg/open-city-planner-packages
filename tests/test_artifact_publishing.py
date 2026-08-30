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
    canonical_public_artifact_url,
    publish_all_from_registry,
    publish_candidate,
    select_all_releases,
    select_release,
    verify_public_release,
)
from scripts.registry import RegistryValidationError
from scripts.verify_artifacts import ArtifactVerificationError, ReleaseCandidate

PAYLOAD = b"analysis-areas immutable artifact bytes"
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()
SOURCE_URL = (
    "https://github.com/oklabflensburg/ocp-module-analysis-areas/releases/download/"
    "v1.0.0/analysis-areas-1.0.0.ocp"
)
PUBLISHED_URL = (
    "https://packages.stadtplaner.oklabflensburg.de/modules/"
    "analysis-areas/1.0.0/analysis-areas-1.0.0.ocp"
)


def write_registry(
    root: Path,
    releases: dict[str, list[tuple[str, str, str]]],
) -> Path:
    registry = root / "registry"
    modules = registry / "modules"
    modules.mkdir(parents=True)
    (registry / "registry.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    for module_id, module_releases in releases.items():
        metadata = {
            "schema_version": 1,
            "id": module_id,
            "name": module_id.replace("-", " ").title(),
            "publisher": {"id": "oklabflensburg", "name": "OK Lab Flensburg"},
            "classification": "first-party",
            "source_repository": f"https://github.com/oklabflensburg/{module_id}",
            "license": "AGPL-3.0-only",
            "versions": [
                {
                    "version": version,
                    "channel": "stable",
                    "artifact": {"url": url, "sha256": sha256},
                    "bundle_format_version": 1,
                    "source_commit": "a" * 40,
                    "source_tag": f"v{version}",
                    "requires": {"host": ">=0.2.0,<1.0.0", "sdk": ">=1.9.0,<2.0.0", "modules": {}},
                }
                for version, url, sha256 in module_releases
            ],
        }
        (modules / f"{module_id}.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
    return registry


def github_release_url(module_id: str, version: str) -> str:
    return (
        f"https://github.com/oklabflensburg/{module_id}/releases/download/"
        f"v{version}/{module_id}-{version}.ocp"
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
    assert release.artifact_url == PUBLISHED_URL
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


def test_bulk_publish_empty_registry_succeeds(tmp_path: Path) -> None:
    registry = write_registry(tmp_path, {})
    result = publish_all_from_registry(
        registry,
        tmp_path / "artifacts",
        downloader=lambda *args, **kwargs: pytest.fail("empty registry must not download"),
    )
    assert result.results == ()
    assert result.published == ()
    assert result.already_present == ()


def test_bulk_publish_multiple_releases_then_reuses_all_existing_files(tmp_path: Path) -> None:
    payloads = {
        "analysis-areas@1.0.0": b"analysis v1",
        "analysis-areas@1.1.0": b"analysis v1.1",
        "energy-map@2.0.0": b"energy v2",
    }
    registry = write_registry(
        tmp_path,
        {
            "analysis-areas": [
                (
                    "1.1.0",
                    github_release_url("analysis-areas", "1.1.0"),
                    hashlib.sha256(payloads["analysis-areas@1.1.0"]).hexdigest(),
                ),
                (
                    "1.0.0",
                    github_release_url("analysis-areas", "1.0.0"),
                    hashlib.sha256(payloads["analysis-areas@1.0.0"]).hexdigest(),
                ),
            ],
            "energy-map": [
                (
                    "2.0.0",
                    github_release_url("energy-map", "2.0.0"),
                    hashlib.sha256(payloads["energy-map@2.0.0"]).hexdigest(),
                )
            ],
        },
    )
    observed_downloads = []

    def downloader(release, destination, timeout, max_bytes):
        observed_downloads.append(release.identity)
        payload = payloads[release.identity]
        destination.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    selected = select_all_releases(registry)
    assert [item.identity for item in selected] == [
        "analysis-areas@1.0.0",
        "analysis-areas@1.1.0",
        "energy-map@2.0.0",
    ]
    first = publish_all_from_registry(registry, tmp_path / "artifacts", downloader=downloader)
    second = publish_all_from_registry(
        registry,
        tmp_path / "artifacts",
        downloader=lambda *args, **kwargs: pytest.fail("existing files must not download"),
    )
    assert len(first.published) == 3
    assert len(second.already_present) == 3
    assert observed_downloads == [item.identity for item in selected]


def test_bulk_publish_keeps_success_before_failure_and_retry_resumes(tmp_path: Path) -> None:
    payloads = {"alpha@1.0.0": b"alpha", "beta@1.0.0": b"beta"}
    registry = write_registry(
        tmp_path,
        {
            module_id: [
                (
                    "1.0.0",
                    github_release_url(module_id, "1.0.0"),
                    hashlib.sha256(payload).hexdigest(),
                )
            ]
            for module_id, payload in (("alpha", b"alpha"), ("beta", b"beta"))
        },
    )
    artifact_root = tmp_path / "artifacts"

    def failing_second_download(release, destination, timeout, max_bytes):
        payload = b"wrong" if release.identity == "beta@1.0.0" else payloads[release.identity]
        destination.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    with pytest.raises(ArtifactPublishingError, match="beta@1.0.0: downloaded SHA-256"):
        publish_all_from_registry(registry, artifact_root, downloader=failing_second_download)
    alpha_target = artifact_root / canonical_artifact_relative_path("alpha", "1.0.0")
    beta_target = artifact_root / canonical_artifact_relative_path("beta", "1.0.0")
    assert alpha_target.read_bytes() == b"alpha"
    assert not beta_target.exists()

    retry_downloads = []

    def retry_download(release, destination, timeout, max_bytes):
        retry_downloads.append(release.identity)
        payload = payloads[release.identity]
        destination.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    retry = publish_all_from_registry(registry, artifact_root, downloader=retry_download)
    assert [item.candidate.identity for item in retry.already_present] == ["alpha@1.0.0"]
    assert [item.candidate.identity for item in retry.published] == ["beta@1.0.0"]
    assert retry_downloads == ["beta@1.0.0"]


def test_canonical_self_mirror_existing_file_is_reused_without_download(tmp_path: Path) -> None:
    registry = write_registry(
        tmp_path,
        {
            "analysis-areas": [
                (
                    "1.0.0",
                    canonical_public_artifact_url("analysis-areas", "1.0.0"),
                    PAYLOAD_SHA256,
                )
            ]
        },
    )
    artifact_root = tmp_path / "artifacts"
    target = artifact_root / canonical_artifact_relative_path("analysis-areas", "1.0.0")
    target.parent.mkdir(parents=True)
    target.write_bytes(PAYLOAD)
    result = publish_all_from_registry(
        registry,
        artifact_root,
        downloader=lambda *args, **kwargs: pytest.fail("self mirror must not download"),
    )
    assert [item.status for item in result.results] == ["already-present"]


def test_canonical_self_mirror_missing_file_fails_without_download(tmp_path: Path) -> None:
    registry = write_registry(
        tmp_path,
        {
            "analysis-areas": [
                (
                    "1.0.0",
                    canonical_public_artifact_url("analysis-areas", "1.0.0"),
                    PAYLOAD_SHA256,
                )
            ]
        },
    )
    with pytest.raises(
        ArtifactPublishingError,
        match="canonical mirror metadata references a missing local artifact",
    ):
        publish_all_from_registry(
            registry,
            tmp_path / "artifacts",
            downloader=lambda *args, **kwargs: pytest.fail("self mirror must fail first"),
        )


def test_public_verification_streams_canonical_url_and_checks_digest(tmp_path: Path) -> None:
    registry = write_registry(
        tmp_path,
        {
            "analysis-areas": [
                (
                    "1.0.0",
                    github_release_url("analysis-areas", "1.0.0"),
                    PAYLOAD_SHA256,
                )
            ]
        },
    )

    def downloader(release, destination, timeout, max_bytes):
        assert release.artifact_url == canonical_public_artifact_url(
            "analysis-areas", "1.0.0"
        )
        destination.write_bytes(PAYLOAD)
        return PAYLOAD_SHA256

    assert verify_public_release(
        registry, "analysis-areas", "1.0.0", downloader=downloader
    ) == canonical_public_artifact_url("analysis-areas", "1.0.0")


def test_public_verification_rejects_wrong_public_digest(tmp_path: Path) -> None:
    registry = write_registry(
        tmp_path,
        {
            "analysis-areas": [
                (
                    "1.0.0",
                    github_release_url("analysis-areas", "1.0.0"),
                    PAYLOAD_SHA256,
                )
            ]
        },
    )
    with pytest.raises(ArtifactPublishingError, match="public SHA-256"):
        verify_public_release(
            registry,
            "analysis-areas",
            "1.0.0",
            downloader=lambda *args, **kwargs: "0" * 64,
        )


def test_bulk_output_is_machine_readable_and_reports_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = write_registry(
        tmp_path,
        {
            "analysis-areas": [
                (
                    "1.0.0",
                    github_release_url("analysis-areas", "1.0.0"),
                    PAYLOAD_SHA256,
                )
            ]
        },
    )
    result = publish_all_from_registry(
        registry, tmp_path / "artifacts", downloader=successful_download()
    )
    publish_artifacts._print_bulk_result(result)
    output = json.loads(capsys.readouterr().out)
    assert output["summary"] == {
        "published": 1,
        "already-present": 0,
        "failed": 0,
    }
    assert output["published"] == [
        {
            "module_id": "analysis-areas",
            "version": "1.0.0",
            "expected_sha256": PAYLOAD_SHA256,
            "public_url": canonical_public_artifact_url("analysis-areas", "1.0.0"),
            "status": "published",
        }
    ]
