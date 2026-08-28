from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from scripts.registry import RegistryValidationError
from scripts.verify_artifacts import (
    HOST_VERIFIER_CONFIG,
    ArtifactVerificationError,
    ReleaseCandidate,
    download_artifact,
    find_new_releases,
    load_host_verifier_contract,
    run_host_verifier,
    validate_redirect_target,
    verify_release_candidates,
)

FIXTURE = Path(__file__).parent / "fixtures" / "valid-registry" / "modules" / "energy-analysis.json"
PAYLOAD = b"valid test artifact bytes"


class ArtifactHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen_user_agent = ""

    def do_GET(self) -> None:
        type(self).seen_user_agent = self.headers.get("User-Agent", "")
        if self.path == "/artifact":
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)
        elif self.path == "/missing":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/oversized-header":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
        elif self.path == "/oversized-stream":
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"x" * 20)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1/forbidden")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/loop")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/slow":
            time.sleep(0.2)
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            with suppress(BrokenPipeError):
                self.wfile.write(PAYLOAD)
        else:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def artifact_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ArtifactHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def module() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def candidate(url: str = "https://example.invalid/artifact.ocp") -> ReleaseCandidate:
    return ReleaseCandidate(
        module_id="energy-analysis",
        version="1.4.0",
        channel="stable",
        artifact_url=url,
        expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        classification="first-party",
    )


def local_url(candidate: ReleaseCandidate):
    return urlsplit(candidate.artifact_url)


def test_new_release_detected(module: dict) -> None:
    base = copy.deepcopy(module)
    current = copy.deepcopy(module)
    release = copy.deepcopy(current["versions"][0])
    release["version"] = "1.5.0"
    release["artifact"]["url"] = release["artifact"]["url"].replace("1.4.0", "1.5.0")
    current["versions"].append(release)
    assert [item.identity for item in find_new_releases([current], [base])] == [
        "energy-analysis@1.5.0"
    ]


def test_unchanged_release_ignored(module: dict) -> None:
    assert find_new_releases([module], [copy.deepcopy(module)]) == []


def test_new_module_detected(module: dict) -> None:
    assert [item.identity for item in find_new_releases([module], [])] == [
        "energy-analysis@1.4.0"
    ]


def test_invalid_url_rejected_before_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def network_must_not_start(*args, **kwargs):
        raise AssertionError("network was opened")

    monkeypatch.setattr("urllib.request.build_opener", network_must_not_start)
    invalid = candidate("http://127.0.0.1/internal.ocp")
    with pytest.raises(RegistryValidationError, match="HTTPS"):
        download_artifact(invalid, tmp_path / "artifact.ocp")


def test_successful_streamed_download_and_user_agent(tmp_path: Path) -> None:
    with artifact_server() as server:
        actual = download_artifact(
            candidate(f"{server}/artifact"),
            tmp_path / "artifact.ocp",
            initial_url_validator=local_url,
        )
    assert actual == hashlib.sha256(PAYLOAD).hexdigest()
    assert ArtifactHandler.seen_user_agent == "OpenCityPlannerRegistryArtifactVerifier/1"


def test_404_fails(tmp_path: Path) -> None:
    with artifact_server() as server, pytest.raises(ArtifactVerificationError, match="HTTP 404"):
        download_artifact(
            candidate(f"{server}/missing"),
            tmp_path / "artifact.ocp",
            initial_url_validator=local_url,
        )


def test_timeout_fails(tmp_path: Path) -> None:
    with artifact_server() as server, pytest.raises(ArtifactVerificationError, match="timed out"):
        download_artifact(
            candidate(f"{server}/slow"),
            tmp_path / "artifact.ocp",
            timeout=0.05,
            initial_url_validator=local_url,
        )


def test_oversized_content_length_fails(tmp_path: Path) -> None:
    with artifact_server() as server, pytest.raises(
        ArtifactVerificationError, match="Content-Length exceeds"
    ):
        download_artifact(
            candidate(f"{server}/oversized-header"),
            tmp_path / "artifact.ocp",
            max_bytes=10,
            initial_url_validator=local_url,
        )


def test_oversized_stream_fails(tmp_path: Path) -> None:
    with artifact_server() as server, pytest.raises(
        ArtifactVerificationError, match="download exceeds"
    ):
        download_artifact(
            candidate(f"{server}/oversized-stream"),
            tmp_path / "artifact.ocp",
            max_bytes=10,
            initial_url_validator=local_url,
        )


def test_forbidden_redirect_fails(tmp_path: Path) -> None:
    with artifact_server() as server, pytest.raises(
        ArtifactVerificationError, match="redirect target"
    ):
        download_artifact(
            candidate(f"{server}/redirect"),
            tmp_path / "artifact.ocp",
            initial_url_validator=local_url,
        )


def test_github_signed_release_asset_redirect_is_allowed() -> None:
    validate_redirect_target(
        "https://release-assets.githubusercontent.com/github-production-release-asset/1/2"
        "?sig=github-generated",
        "github.com",
    )


def test_redirect_loop_is_bounded(tmp_path: Path) -> None:
    with artifact_server() as server, pytest.raises(
        ArtifactVerificationError, match="redirect limit"
    ):
        download_artifact(
            candidate(f"{server}/loop"),
            tmp_path / "artifact.ocp",
            max_redirects=2,
            initial_url_validator=local_url,
            redirect_target_validator=lambda target, initial: None,
        )


def test_sha_mismatch_skips_verifier_and_cleans_temp(tmp_path: Path) -> None:
    artifact_paths: list[Path] = []
    verifier_called = False

    def downloader(candidate, path, timeout, max_bytes):
        artifact_paths.append(path)
        path.write_bytes(PAYLOAD)
        return "0" * 64

    def verifier(candidate, path, host_root, state_root):
        nonlocal verifier_called
        verifier_called = True

    with pytest.raises(ArtifactVerificationError, match="SHA-256 does not match"):
        verify_release_candidates(
            [candidate()],
            tmp_path,
            downloader=downloader,
            verifier=verifier,
            validate_checkout=lambda root: None,
        )
    assert not verifier_called
    assert artifact_paths and not artifact_paths[0].exists()


def test_host_verifier_failure_fails(tmp_path: Path) -> None:
    def downloader(candidate, path, timeout, max_bytes):
        path.write_bytes(PAYLOAD)
        return candidate.expected_sha256

    def verifier(candidate, path, host_root, state_root):
        raise ArtifactVerificationError("host verifier failed")

    with pytest.raises(ArtifactVerificationError, match="host verifier failed"):
        verify_release_candidates(
            [candidate()],
            tmp_path,
            downloader=downloader,
            verifier=verifier,
            validate_checkout=lambda root: None,
        )


def test_digest_and_host_verifier_success(tmp_path: Path) -> None:
    calls = []

    def downloader(candidate, path, timeout, max_bytes):
        path.write_bytes(PAYLOAD)
        return candidate.expected_sha256

    def verifier(candidate, path, host_root, state_root):
        calls.append((candidate.identity, path.is_file()))

    verify_release_candidates(
        [candidate()],
        tmp_path,
        downloader=downloader,
        verifier=verifier,
        validate_checkout=lambda root: None,
    )
    assert calls == [("energy-analysis@1.4.0", True)]


def test_empty_candidate_set_passes_without_checkout(tmp_path: Path) -> None:
    verify_release_candidates(
        [],
        tmp_path / "missing",
        validate_checkout=lambda root: pytest.fail("checkout should not be validated"),
    )


def test_host_verifier_uses_argv_shell_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host_root = tmp_path / "host"
    python = host_root / "backend" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    artifact = tmp_path / "safe artifact.ocp"
    artifact.touch()
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"module_id": "energy-analysis", "version": "1.4.0"}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_host_verifier(candidate(), artifact, host_root, tmp_path / "state")
    assert observed["kwargs"]["shell"] is False
    assert observed["argv"][-2:] == ["verify", str(artifact)]
    assert observed["argv"][0] == str(python.resolve())


def test_metadata_cannot_inject_host_verifier_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host_root = tmp_path / "host"
    python = host_root / "backend" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    malicious = replace(candidate(), module_id="$(touch injected); rm -rf /")
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["shell"] = kwargs["shell"]
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"module_id": malicious.module_id, "version": malicious.version}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_host_verifier(malicious, tmp_path / "artifact.ocp", host_root, tmp_path / "state")
    assert observed["shell"] is False
    assert malicious.module_id not in observed["argv"]


def test_registry_identity_must_match_verified_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host_root = tmp_path / "host"
    python = host_root / "backend" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"module_id": "other-module", "version": "1.4.0"}),
            stderr="",
        ),
    )
    with pytest.raises(ArtifactVerificationError, match="identity does not match"):
        run_host_verifier(candidate(), tmp_path / "artifact.ocp", host_root, tmp_path / "state")


def test_host_pin_has_one_full_commit_source_of_truth() -> None:
    contract = load_host_verifier_contract()
    assert HOST_VERIFIER_CONFIG.is_file()
    assert len(contract["OCP_HOST_VERIFIER_REF"]) == 40
    assert contract["OCP_HOST_VERIFIER_REPOSITORY"] == "oklabflensburg/open-city-planner"
