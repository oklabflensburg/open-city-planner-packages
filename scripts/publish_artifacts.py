#!/usr/bin/env python3
"""Publish one validated Registry v1 release into the immutable artifact mirror."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from .registry import (
        RegistryValidationError,
        load_registry,
        validate_module_id,
        validate_semver,
    )
    from .verify_artifacts import (
        DEFAULT_TIMEOUT,
        MAX_ARTIFACT_BYTES,
        ArtifactVerificationError,
        DownloadFunction,
        ReleaseCandidate,
        VerifierFunction,
        download_artifact,
        run_host_verifier,
        validate_candidate_url,
        validate_host_verifier_checkout,
    )
else:
    from verify_artifacts import (
        DEFAULT_TIMEOUT,
        MAX_ARTIFACT_BYTES,
        ArtifactVerificationError,
        DownloadFunction,
        ReleaseCandidate,
        VerifierFunction,
        download_artifact,
        run_host_verifier,
        validate_candidate_url,
        validate_host_verifier_checkout,
    )

    from registry import (
        RegistryValidationError,
        load_registry,
        validate_module_id,
        validate_semver,
    )

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FILE_MODE = 0o644
DIRECTORY_MODE = 0o755
STATUS_PUBLISHED = "published"
STATUS_ALREADY_PRESENT = "already-present"


class ArtifactPublishingError(RuntimeError):
    """Raised when an artifact cannot be published without weakening immutability."""


@dataclass(frozen=True)
class PublishResult:
    candidate: ReleaseCandidate
    target_path: Path
    status: str


def select_release(
    registry_root: Path, module_id: str, version: str
) -> ReleaseCandidate:
    """Select one release only after Registry v1 validates the complete source."""

    canonical_id = validate_module_id(module_id, "--module")
    canonical_version = validate_semver(version, "--version")
    modules = load_registry(registry_root)
    module = next((item for item in modules if item["id"] == canonical_id), None)
    if module is None:
        raise ArtifactPublishingError(f'module "{canonical_id}" is not published')
    release = next(
        (item for item in module["versions"] if item["version"] == canonical_version),
        None,
    )
    if release is None:
        raise ArtifactPublishingError(
            f'release "{canonical_id}@{canonical_version}" is not published'
        )
    candidate = ReleaseCandidate(
        module_id=canonical_id,
        version=canonical_version,
        channel=release["channel"],
        artifact_url=release["artifact"]["url"],
        expected_sha256=release["artifact"]["sha256"],
        classification=module["classification"],
    )
    validate_candidate_url(candidate)
    return candidate


def canonical_artifact_relative_path(module_id: str, version: str) -> Path:
    """Derive the only public mirror path from canonical Registry v1 identity."""

    canonical_id = validate_module_id(module_id)
    canonical_version = validate_semver(version)
    return (
        Path("modules")
        / canonical_id
        / canonical_version
        / f"{canonical_id}-{canonical_version}.ocp"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_publish_directory(artifact_root: Path, relative_parent: Path) -> Path:
    if not artifact_root.is_absolute():
        raise ArtifactPublishingError("artifact root must be an absolute path")
    artifact_root.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
    if artifact_root.is_symlink() or not artifact_root.is_dir():
        raise ArtifactPublishingError("artifact root must be a real directory")
    os.chmod(artifact_root, DIRECTORY_MODE)
    root = artifact_root.resolve(strict=True)
    current = root
    for component in relative_parent.parts:
        current = current / component
        if current.is_symlink():
            raise ArtifactPublishingError("artifact path must not contain symlinks")
        current.mkdir(exist_ok=True, mode=DIRECTORY_MODE)
        if current.is_symlink() or not current.is_dir():
            raise ArtifactPublishingError("artifact path must contain only directories")
        os.chmod(current, DIRECTORY_MODE)
    if not current.resolve(strict=True).is_relative_to(root):
        raise ArtifactPublishingError("artifact target escapes the configured root")
    return current


def _existing_status(target: Path, expected_sha256: str) -> str | None:
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise ArtifactPublishingError("existing artifact target is not a regular file")
    actual_sha256 = sha256_file(target)
    if actual_sha256 != expected_sha256:
        raise ArtifactPublishingError(
            "existing artifact SHA-256 does not match Registry metadata; refusing overwrite"
        )
    return STATUS_ALREADY_PRESENT


def _new_partial_path(parent: Path, filename: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{filename}.", suffix=".partial", dir=parent
    )
    os.close(descriptor)
    partial = Path(raw_path)
    partial.unlink()
    return partial


def _sync_file(path: Path) -> None:
    with path.open("rb") as artifact:
        os.fsync(artifact.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_partial_artifact(
    candidate: ReleaseCandidate,
    partial: Path,
    host_verifier_root: Path,
    verifier: VerifierFunction,
) -> None:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{candidate.module_id}-{candidate.version}.",
        suffix=".verify.ocp",
        dir=partial.parent,
    )
    os.close(descriptor)
    verifier_path = Path(raw_path)
    verifier_path.unlink()
    try:
        os.link(partial, verifier_path)
        with tempfile.TemporaryDirectory(prefix="ocp-mirror-host-state-") as temporary:
            verifier(candidate, verifier_path, host_verifier_root, Path(temporary))
    finally:
        verifier_path.unlink(missing_ok=True)


def publish_candidate(
    candidate: ReleaseCandidate,
    artifact_root: Path,
    *,
    host_verifier_root: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_ARTIFACT_BYTES,
    downloader: DownloadFunction = download_artifact,
    verifier: VerifierFunction = run_host_verifier,
    validate_checkout: Callable[[Path], None] = validate_host_verifier_checkout,
) -> PublishResult:
    """Download, validate, and atomically publish one candidate without overwrite."""

    validate_candidate_url(candidate)
    relative = canonical_artifact_relative_path(candidate.module_id, candidate.version)
    parent = _ensure_publish_directory(artifact_root, relative.parent)
    target = parent / relative.name
    existing = _existing_status(target, candidate.expected_sha256)
    if existing is not None:
        return PublishResult(candidate, target, existing)

    if host_verifier_root is not None:
        validate_checkout(host_verifier_root)

    partial = _new_partial_path(parent, relative.name)
    try:
        actual_sha256 = downloader(candidate, partial, timeout, max_bytes)
        if actual_sha256 != candidate.expected_sha256:
            raise ArtifactPublishingError(
                f"{candidate.identity}: downloaded SHA-256 does not match Registry metadata"
            )
        if host_verifier_root is not None:
            _verify_partial_artifact(candidate, partial, host_verifier_root, verifier)
        os.chmod(partial, FILE_MODE)
        _sync_file(partial)
        try:
            os.link(partial, target)
        except FileExistsError as exc:
            status = _existing_status(target, candidate.expected_sha256)
            if status is None:  # pragma: no cover - target disappeared during the race
                raise ArtifactPublishingError(
                    "artifact publication raced with target removal"
                ) from exc
            return PublishResult(candidate, target, status)
        _sync_directory(parent)
        return PublishResult(candidate, target, STATUS_PUBLISHED)
    except (ArtifactVerificationError, OSError) as exc:
        raise ArtifactPublishingError(str(exc)) from exc
    finally:
        partial.unlink(missing_ok=True)


def publish_from_registry(
    registry_root: Path,
    module_id: str,
    version: str,
    artifact_root: Path,
    **kwargs: Any,
) -> PublishResult:
    candidate = select_release(registry_root, module_id, version)
    return publish_candidate(candidate, artifact_root, **kwargs)


def _print_result(result: PublishResult) -> None:
    print(f"module: {result.candidate.module_id}")
    print(f"version: {result.candidate.version}")
    print(f"source URL: {result.candidate.artifact_url}")
    print(f"expected SHA: {result.candidate.expected_sha256}")
    print(f"target path: {result.target_path}")
    print(f"status: {result.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True, help="published Registry v1 module ID")
    parser.add_argument("--version", required=True, help="published complete SemVer")
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=REPOSITORY_ROOT / "registry")
    parser.add_argument("--host-verifier-root", type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()
    try:
        result = publish_from_registry(
            args.registry,
            args.module,
            args.version,
            args.artifact_root,
            host_verifier_root=args.host_verifier_root,
            timeout=args.timeout,
        )
    except (
        ArtifactPublishingError,
        ArtifactVerificationError,
        RegistryValidationError,
        OSError,
    ) as exc:
        print(f"artifact publication failed: {exc}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
