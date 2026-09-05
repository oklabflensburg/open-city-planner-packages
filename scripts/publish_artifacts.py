#!/usr/bin/env python3
"""Publish validated Registry v1 releases into the immutable artifact mirror."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from .artifact_store import (
        STATUS_ALREADY_PRESENT,
        STATUS_PUBLISHED,
        ArtifactNotFound,
        ArtifactStoreError,
        FilesystemArtifactStore,
        canonical_artifact_relative_path,
        canonical_public_artifact_url,
    )
    from .registry import (
        CANONICAL_REGISTRY_HOST,
        RegistryValidationError,
        load_registry,
        semver_key,
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
    from artifact_store import (
        STATUS_ALREADY_PRESENT,
        STATUS_PUBLISHED,
        ArtifactNotFound,
        ArtifactStoreError,
        FilesystemArtifactStore,
        canonical_artifact_relative_path,
        canonical_public_artifact_url,
    )
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
        CANONICAL_REGISTRY_HOST,
        RegistryValidationError,
        load_registry,
        semver_key,
        validate_module_id,
        validate_semver,
    )

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# Preserve the established mirror exception interface while sharing the storage core.
ArtifactPublishingError = ArtifactStoreError


@dataclass(frozen=True)
class PublishResult:
    candidate: ReleaseCandidate
    target_path: Path
    status: str


@dataclass(frozen=True)
class BulkPublishResult:
    results: tuple[PublishResult, ...]

    @property
    def published(self) -> tuple[PublishResult, ...]:
        return tuple(result for result in self.results if result.status == STATUS_PUBLISHED)

    @property
    def already_present(self) -> tuple[PublishResult, ...]:
        return tuple(result for result in self.results if result.status == STATUS_ALREADY_PRESENT)


def _candidate_from_release(module: dict[str, Any], release: dict[str, Any]) -> ReleaseCandidate:
    candidate = ReleaseCandidate(
        module_id=module["id"],
        version=release["version"],
        channel=release["channel"],
        artifact_url=release["artifact"]["url"],
        expected_sha256=release["artifact"]["sha256"],
        classification=module["classification"],
    )
    validate_candidate_url(candidate)
    return candidate


def select_release(registry_root: Path, module_id: str, version: str) -> ReleaseCandidate:
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
    return _candidate_from_release(module, release)


def select_all_releases(registry_root: Path) -> list[ReleaseCandidate]:
    """Select every published release from one completely validated Registry source."""

    candidates = [
        _candidate_from_release(module, release)
        for module in load_registry(registry_root)
        for release in module["versions"]
    ]
    return sorted(candidates, key=lambda item: (item.module_id, semver_key(item.version)))


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

    source = validate_candidate_url(candidate)
    store = FilesystemArtifactStore(artifact_root)
    relative = canonical_artifact_relative_path(candidate.module_id, candidate.version)
    target = artifact_root / relative
    try:
        store.verify(candidate.module_id, candidate.version, candidate.expected_sha256)
    except ArtifactNotFound:
        pass
    else:
        # Reuse the same durable no-op path after a previous post-link failure.
        result = store.publish(
            candidate.module_id, candidate.version, target, candidate.expected_sha256
        )
        return PublishResult(candidate, target, result.status)

    if source.hostname == CANONICAL_REGISTRY_HOST:
        raise ArtifactPublishingError(
            f"{candidate.identity}: canonical mirror metadata references a missing local artifact"
        )
    if host_verifier_root is not None:
        validate_checkout(host_verifier_root)
    # Intake stays private and outside HTTP serving. The storage core makes its own
    # same-filesystem copy, independently hashes it and performs the only final link.
    with tempfile.TemporaryDirectory(prefix="ocp-mirror-intake-") as temporary:
        partial = Path(temporary) / f".{relative.name}.download.partial"
        try:
            actual_sha256 = downloader(candidate, partial, timeout, max_bytes)
            if actual_sha256 != candidate.expected_sha256:
                raise ArtifactPublishingError(
                    f"{candidate.identity}: downloaded SHA-256 does not match Registry metadata"
                )
            if host_verifier_root is not None:
                _verify_partial_artifact(candidate, partial, host_verifier_root, verifier)
            result = store.publish(
                candidate.module_id, candidate.version, partial, candidate.expected_sha256
            )
            return PublishResult(candidate, target, result.status)
        except ArtifactVerificationError as exc:
            raise ArtifactPublishingError(str(exc)) from exc
        except OSError:
            raise ArtifactPublishingError("Artifact intake failed") from None


def publish_from_registry(
    registry_root: Path,
    module_id: str,
    version: str,
    artifact_root: Path,
    **kwargs: Any,
) -> PublishResult:
    candidate = select_release(registry_root, module_id, version)
    return publish_candidate(candidate, artifact_root, **kwargs)


def publish_all_from_registry(
    registry_root: Path,
    artifact_root: Path,
    **kwargs: Any,
) -> BulkPublishResult:
    """Publish every reviewed release, preserving successful append-only progress."""

    results = []
    for candidate in select_all_releases(registry_root):
        try:
            results.append(publish_candidate(candidate, artifact_root, **kwargs))
        except (ArtifactPublishingError, ArtifactVerificationError, OSError) as exc:
            if str(exc).startswith(f"{candidate.identity}:"):
                raise
            raise ArtifactPublishingError(f"{candidate.identity}: {exc}") from exc
    return BulkPublishResult(tuple(results))


def verify_public_release(
    registry_root: Path,
    module_id: str,
    version: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_ARTIFACT_BYTES,
    downloader: DownloadFunction = download_artifact,
) -> str:
    """Stream the canonical public artifact and require its reviewed digest."""

    selected = select_release(registry_root, module_id, version)
    public_url = canonical_public_artifact_url(module_id, version)
    public_candidate = ReleaseCandidate(
        module_id=selected.module_id,
        version=selected.version,
        channel=selected.channel,
        artifact_url=public_url,
        expected_sha256=selected.expected_sha256,
        classification=selected.classification,
    )
    validate_candidate_url(public_candidate)
    with tempfile.TemporaryDirectory(prefix="ocp-public-artifact-") as temporary:
        artifact = Path(temporary) / f"{module_id}-{version}.ocp"
        actual_sha256 = downloader(public_candidate, artifact, timeout, max_bytes)
    if actual_sha256 != selected.expected_sha256:
        raise ArtifactPublishingError(
            f"{selected.identity}: public SHA-256 does not match Registry metadata"
        )
    return public_url


def _print_result(result: PublishResult) -> None:
    print(f"module: {result.candidate.module_id}")
    print(f"version: {result.candidate.version}")
    print(f"source URL: {result.candidate.artifact_url}")
    print(f"expected SHA: {result.candidate.expected_sha256}")
    print(f"target path: {result.target_path}")
    print(f"status: {result.status}")


def _serialized_result(result: PublishResult) -> dict[str, str]:
    return {
        "module_id": result.candidate.module_id,
        "version": result.candidate.version,
        "expected_sha256": result.candidate.expected_sha256,
        "public_url": canonical_public_artifact_url(
            result.candidate.module_id, result.candidate.version
        ),
        "status": result.status,
    }


def _print_bulk_result(result: BulkPublishResult) -> None:
    payload = {
        "published": [_serialized_result(item) for item in result.published],
        "already_present": [_serialized_result(item) for item in result.already_present],
        "summary": {
            "published": len(result.published),
            "already-present": len(result.already_present),
            "failed": 0,
        },
    }
    print(json.dumps(payload, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", help="published Registry v1 module ID")
    parser.add_argument("--version", help="published complete SemVer")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="publish every reviewed release")
    mode.add_argument(
        "--verify-public",
        action="store_true",
        help="stream and verify one release from its canonical public mirror URL",
    )
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--registry", type=Path, default=REPOSITORY_ROOT / "registry")
    parser.add_argument("--host-verifier-root", type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()
    if args.all:
        if args.module is not None or args.version is not None or args.artifact_root is None:
            parser.error("--all requires --artifact-root and does not accept --module/--version")
    elif args.verify_public:
        if args.module is None or args.version is None or args.artifact_root is not None:
            parser.error("--verify-public requires --module and --version only")
    elif args.module is None or args.version is None or args.artifact_root is None:
        parser.error("single publication requires --module, --version, and --artifact-root")
    try:
        if args.all:
            bulk_result = publish_all_from_registry(
                args.registry,
                args.artifact_root,
                host_verifier_root=args.host_verifier_root,
                timeout=args.timeout,
            )
            _print_bulk_result(bulk_result)
        elif args.verify_public:
            public_url = verify_public_release(
                args.registry,
                args.module,
                args.version,
                timeout=args.timeout,
            )
            print(f"public artifact verified: {public_url}")
        else:
            result = publish_from_registry(
                args.registry,
                args.module,
                args.version,
                args.artifact_root,
                host_verifier_root=args.host_verifier_root,
                timeout=args.timeout,
            )
            _print_result(result)
    except (
        ArtifactPublishingError,
        ArtifactVerificationError,
        RegistryValidationError,
        OSError,
    ) as exc:
        print(f"artifact publication failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
