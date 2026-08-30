#!/usr/bin/env python3
"""Verify new Registry v1 release artifacts with the pinned host contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

if __package__:
    from .registry import (
        RegistryValidationError,
        load_registry,
        load_registry_from_git,
        semver_key,
        validate_artifact_url,
    )
else:
    from registry import (
        RegistryValidationError,
        load_registry,
        load_registry_from_git,
        semver_key,
        validate_artifact_url,
    )

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HOST_VERIFIER_CONFIG = REPOSITORY_ROOT / ".github" / "ocp-host-verifier.json"
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_DOWNLOAD_SECONDS = 600.0
HOST_VERIFIER_TIMEOUT = 600.0
DEFAULT_TIMEOUT = 30.0
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
USER_AGENT = "OpenCityPlannerRegistryArtifactVerifier/1"
GITHUB_RELEASE_REDIRECT_HOSTS = frozenset({"release-assets.githubusercontent.com"})


class ArtifactVerificationError(RuntimeError):
    """Raised when a release artifact cannot be safely verified."""


@dataclass(frozen=True)
class ReleaseCandidate:
    module_id: str
    version: str
    channel: str
    artifact_url: str
    expected_sha256: str
    classification: str

    @property
    def identity(self) -> str:
        return f"{self.module_id}@{self.version}"


def find_new_releases(
    current_modules: list[dict[str, Any]], base_modules: list[dict[str, Any]]
) -> list[ReleaseCandidate]:
    """Return releases whose module ID and version do not exist in the base registry."""

    published = {
        (module["id"], release["version"])
        for module in base_modules
        for release in module["versions"]
    }
    candidates = []
    for module in current_modules:
        for release in module["versions"]:
            identity = (module["id"], release["version"])
            if identity not in published:
                candidates.append(
                    ReleaseCandidate(
                        module_id=module["id"],
                        version=release["version"],
                        channel=release["channel"],
                        artifact_url=release["artifact"]["url"],
                        expected_sha256=release["artifact"]["sha256"],
                        classification=module["classification"],
                    )
                )
    return sorted(candidates, key=lambda item: (item.module_id, semver_key(item.version)))


def validate_candidate_url(candidate: ReleaseCandidate) -> SplitResult:
    return validate_artifact_url(
        candidate.artifact_url,
        candidate.classification,
        candidate.module_id,
        candidate.version,
        f"{candidate.identity} artifact URL",
    )


def validate_redirect_target(target_url: str, initial_hostname: str) -> None:
    """Allow only GitHub's observed HTTPS release-asset redirect service."""

    parsed = urlsplit(target_url)
    try:
        invalid_port = parsed.port not in {None, 443}
    except ValueError:
        invalid_port = True
    if (
        initial_hostname != "github.com"
        or parsed.scheme != "https"
        or parsed.hostname not in GITHUB_RELEASE_REDIRECT_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or invalid_port
        or parsed.fragment
        or not parsed.path.startswith("/github-production-release-asset/")
        or "\\" in target_url
        or any(character.isspace() or ord(character) < 32 for character in target_url)
    ):
        raise ArtifactVerificationError("artifact redirect target is not policy-approved")


class _PolicyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(
        self,
        initial_hostname: str,
        validator: Callable[[str, str], None],
        max_redirects: int,
    ) -> None:
        super().__init__()
        self.initial_hostname = initial_hostname
        self.validator = validator
        self.max_redirects = max_redirects
        self.redirects = 0

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        self.redirects += 1
        if self.redirects > self.max_redirects:
            raise ArtifactVerificationError("artifact redirect limit exceeded")
        self.validator(new_url, self.initial_hostname)
        redirected = super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )
        if redirected is not None:
            redirected.add_header("User-Agent", USER_AGENT)
        return redirected


def download_artifact(
    candidate: ReleaseCandidate,
    destination: Path,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_ARTIFACT_BYTES,
    *,
    max_download_seconds: float = MAX_DOWNLOAD_SECONDS,
    max_redirects: int = MAX_REDIRECTS,
    initial_url_validator: Callable[[ReleaseCandidate], SplitResult] = validate_candidate_url,
    redirect_target_validator: Callable[[str, str], None] = validate_redirect_target,
) -> str:
    """Stream one policy-approved artifact to disk and return its SHA-256."""

    if timeout <= 0 or max_download_seconds <= 0 or max_bytes <= 0 or max_redirects < 0:
        raise ArtifactVerificationError("download limits must be positive")
    initial = initial_url_validator(candidate)
    if not initial.hostname:
        raise ArtifactVerificationError("artifact URL has no hostname")
    redirect_handler = _PolicyRedirectHandler(
        initial.hostname, redirect_target_validator, max_redirects
    )
    opener = urllib.request.build_opener(redirect_handler)
    request = urllib.request.Request(
        candidate.artifact_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"},
        method="GET",
    )
    digest = hashlib.sha256()
    downloaded = 0
    deadline = time.monotonic() + max_download_seconds
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.getcode()
            if status is None or not 200 <= status < 300:
                raise ArtifactVerificationError(f"artifact request returned HTTP {status}")
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError as exc:
                    raise ArtifactVerificationError("artifact Content-Length is invalid") from exc
                if declared_size < 0 or declared_size > max_bytes:
                    raise ArtifactVerificationError("artifact Content-Length exceeds size limit")
            with destination.open("xb") as output:
                while True:
                    if time.monotonic() > deadline:
                        raise ArtifactVerificationError("artifact download exceeded total timeout")
                    chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, max_bytes + 1 - downloaded))
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise ArtifactVerificationError("artifact download exceeds size limit")
                    digest.update(chunk)
                    output.write(chunk)
    except ArtifactVerificationError:
        raise
    except urllib.error.HTTPError as exc:
        raise ArtifactVerificationError(f"artifact request failed with HTTP {exc.code}") from exc
    except TimeoutError as exc:
        raise ArtifactVerificationError("artifact request timed out") from exc
    except urllib.error.URLError as exc:
        reason = "timeout" if isinstance(exc.reason, TimeoutError) else type(exc.reason).__name__
        raise ArtifactVerificationError(f"artifact network request failed ({reason})") from exc
    except OSError as exc:
        raise ArtifactVerificationError(f"artifact download failed ({type(exc).__name__})") from exc
    return digest.hexdigest()


def load_host_verifier_contract() -> dict[str, str]:
    try:
        contract = json.loads(HOST_VERIFIER_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(f"invalid host verifier config: {exc}") from exc
    required = {"OCP_HOST_VERIFIER_REPOSITORY", "OCP_HOST_VERIFIER_REF"}
    if not isinstance(contract, dict) or set(contract) != required:
        raise ArtifactVerificationError("host verifier config has unknown or missing fields")
    reference = contract["OCP_HOST_VERIFIER_REF"]
    if not isinstance(reference, str) or len(reference) != 40 or any(
        character not in "0123456789abcdef" for character in reference
    ):
        raise ArtifactVerificationError("host verifier ref must be a full lowercase commit SHA")
    if contract["OCP_HOST_VERIFIER_REPOSITORY"] != "oklabflensburg/open-city-planner":
        raise ArtifactVerificationError("host verifier repository is not policy-approved")
    return contract


def validate_host_verifier_checkout(host_root: Path) -> None:
    contract = load_host_verifier_contract()
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=host_root,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0 or result.stdout.strip() != contract["OCP_HOST_VERIFIER_REF"]:
        raise ArtifactVerificationError("host verifier checkout does not match the pinned commit")
    python = host_root / "backend" / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ArtifactVerificationError("pinned host verifier environment is not installed")


def run_host_verifier(
    candidate: ReleaseCandidate, artifact_path: Path, host_root: Path, state_root: Path
) -> None:
    """Run only the pinned host's read-only verify CLI and compare bundle identity."""

    python = (host_root / "backend" / ".venv" / "bin" / "python").absolute()
    try:
        result = subprocess.run(
            [
                str(python),
                "-m",
                "app.cli.modules",
                "--root",
                str(state_root),
                "verify",
                str(artifact_path),
            ],
            cwd=host_root / "backend",
            check=False,
            capture_output=True,
            env={**os.environ, "OCP_EXCLUDED_BUILTIN_MODULES": candidate.module_id},
            text=True,
            shell=False,
            timeout=HOST_VERIFIER_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise ArtifactVerificationError(
            f"{candidate.identity}: host verifier timed out"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "no verifier details"
        raise ArtifactVerificationError(f"{candidate.identity}: host verifier failed: {detail}")
    try:
        output_lines = result.stdout.splitlines()
        verified = json.loads(output_lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(
            f"{candidate.identity}: host verifier returned invalid JSON"
        ) from exc
    if not isinstance(verified, dict):
        raise ArtifactVerificationError(
            f"{candidate.identity}: host verifier JSON must be an object"
        )
    identity_mismatch = (
        verified.get("module_id") != candidate.module_id
        or verified.get("version") != candidate.version
    )
    if identity_mismatch:
        raise ArtifactVerificationError(
            f"{candidate.identity}: registry identity does not match verified bundle identity"
        )
    if (state_root / "modules.lock").exists():
        raise ArtifactVerificationError("host verify unexpectedly created modules.lock")


DownloadFunction = Callable[[ReleaseCandidate, Path, float, int], str]
VerifierFunction = Callable[[ReleaseCandidate, Path, Path, Path], None]


def verify_release_candidates(
    candidates: list[ReleaseCandidate],
    host_verifier_root: Path,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_ARTIFACT_BYTES,
    *,
    downloader: DownloadFunction = download_artifact,
    verifier: VerifierFunction = run_host_verifier,
    validate_checkout: Callable[[Path], None] = validate_host_verifier_checkout,
) -> None:
    if not candidates:
        print("No new release artifacts to verify.")
        return
    validate_checkout(host_verifier_root)
    for candidate in candidates:
        print(f"verifying {candidate.identity}")
        with tempfile.TemporaryDirectory(prefix="ocp-registry-artifact-") as temporary:
            temporary_root = Path(temporary)
            artifact = temporary_root / f"{candidate.module_id}-{candidate.version}.ocp"
            actual_sha256 = downloader(candidate, artifact, timeout, max_bytes)
            print("download ok")
            if actual_sha256 != candidate.expected_sha256:
                raise ArtifactVerificationError(
                    f"{candidate.identity}: SHA-256 does not match registry metadata"
                )
            print("sha256 ok")
            verifier(candidate, artifact, host_verifier_root, temporary_root / "host-state")
            print("host verifier ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="published base Git reference")
    parser.add_argument("--host-verifier-root", type=Path)
    parser.add_argument("--registry", type=Path, default=REPOSITORY_ROOT / "registry")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--count-only", action="store_true")
    args = parser.parse_args()
    try:
        current = load_registry(args.registry)
        base = load_registry_from_git(args.base_ref, REPOSITORY_ROOT)
        candidates = find_new_releases(current, base)
        if args.count_only:
            print(len(candidates))
            return 0
        if candidates and args.host_verifier_root is None:
            raise ArtifactVerificationError("--host-verifier-root is required for new releases")
        verify_release_candidates(candidates, args.host_verifier_root or Path("."), args.timeout)
    except (OSError, RegistryValidationError, ArtifactVerificationError) as exc:
        print(f"artifact verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
