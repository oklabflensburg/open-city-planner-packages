"""Immutable artifact storage, independent of Registry, downloads and application deploys.

The filesystem backend requires POSIX dir_fd/O_NOFOLLOW, hardlinks and fsync.
Only trusted publishers may modify its directories; there is no replace/delete API.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4

if __package__:
    from .registry import (
        CANONICAL_REGISTRY_HOST,
        SHA256_RE,
        RegistryValidationError,
        validate_module_id,
        validate_semver,
    )
else:
    from registry import (
        CANONICAL_REGISTRY_HOST,
        SHA256_RE,
        RegistryValidationError,
        validate_module_id,
        validate_semver,
    )


FILE_MODE = 0o644
DIRECTORY_MODE = 0o755
STATUS_PUBLISHED = "published"
STATUS_ALREADY_PRESENT = "already-present"
_UNSPECIFIED = object()


class ArtifactStoreError(RuntimeError):
    """Storage operation failed; callers must not assume durable publication."""


class ArtifactConflict(ArtifactStoreError):
    """A version is already bound to other bytes, or stored bytes are corrupt."""


class InvalidArtifact(ArtifactStoreError):
    """Invalid identity, digest, source or unsafe filesystem path."""


class ArtifactNotFound(ArtifactStoreError):
    """No stored version exists."""


@dataclass(frozen=True)
class StoredArtifact:
    module_id: str
    version: str
    digest_algorithm: str
    digest: str
    byte_size: int
    storage_locator: str
    public_url: str


@dataclass(frozen=True)
class Publication:
    artifact: StoredArtifact
    status: str


class ArtifactStore(Protocol):
    def publish(
        self, module_id: str, version: str, source: Path, expected_sha256: str
    ) -> Publication: ...

    def verify(self, module_id: str, version: str, expected_sha256: str) -> StoredArtifact: ...

    def exists(self, module_id: str, version: str) -> bool: ...

    def public_url(self, module_id: str, version: str) -> str: ...


# Reused by the existing mirror CLI; preserve its validation exception contract.
def canonical_artifact_relative_path(module_id: str, version: str) -> Path:
    module_id = validate_module_id(module_id)
    version = validate_semver(version)
    return Path("modules") / module_id / version / f"{module_id}-{version}.ocp"


def canonical_public_artifact_url(module_id: str, version: str) -> str:
    key = canonical_artifact_relative_path(module_id, version).as_posix()
    return f"https://{CANONICAL_REGISTRY_HOST}/{key}"


def _identity(module_id: str, version: str, digest: str | object = _UNSPECIFIED) -> Path:
    try:
        relative = canonical_artifact_relative_path(module_id, version)
    except RegistryValidationError:
        raise InvalidArtifact("Invalid module ID or SemVer") from None
    if digest is not _UNSPECIFIED and (
        not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
    ):
        raise InvalidArtifact("Expected SHA-256 must be 64 lowercase hex characters")
    return relative


def _safe_absolute(path: Path) -> Path:
    if ".." in path.parts or "\x00" in str(path) or "\\" in str(path):
        raise InvalidArtifact("Path contains forbidden components")
    return path.absolute()


@contextmanager
def _directory(path: Path, *, create: bool = False, mode: int = DIRECTORY_MODE) -> Iterator[int]:
    """Walk from / with pinned descriptors; never follow a symlink in any component."""
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            created = False
            if create:
                try:
                    os.mkdir(component, mode=mode, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    pass
            try:
                child = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                raise
            except OSError:
                raise InvalidArtifact(
                    "Directory path must not contain symlinks or non-directories"
                ) from None
            try:
                if created:
                    os.fchmod(child, mode)
                    os.fsync(child)
                    os.fsync(descriptor)
            except BaseException:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _regular_file(parent: int, name: str) -> Iterator[BinaryIO]:
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent
        )
    except FileNotFoundError:
        raise
    except OSError:
        raise InvalidArtifact("File must be readable and must not be a symlink") from None
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise InvalidArtifact("Artifact must be a regular file")
    with os.fdopen(descriptor, "rb") as stream:
        yield stream


def _digest(stream: BinaryIO) -> tuple[str, int]:
    stream.seek(0)
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


class FilesystemArtifactStore:
    def __init__(self, root: Path):
        if not root.is_absolute() or root == Path("/"):
            raise InvalidArtifact("Artifact root must be an explicit absolute directory")
        self.root = _safe_absolute(root)
        if "releases" in self.root.parts or "current" in self.root.parts:
            raise InvalidArtifact("Artifact root must be outside application releases/current")

    @classmethod
    def from_environment(cls) -> FilesystemArtifactStore:
        value = os.environ.get("PACKAGES_REGISTRY_ARTIFACT_ROOT")
        if not value:
            raise InvalidArtifact("PACKAGES_REGISTRY_ARTIFACT_ROOT is required")
        return cls(Path(value))

    def public_url(self, module_id: str, version: str) -> str:
        _identity(module_id, version)
        return canonical_public_artifact_url(module_id, version)

    def _metadata(self, module_id: str, version: str, digest: str, size: int) -> StoredArtifact:
        return StoredArtifact(
            module_id,
            version,
            "sha256",
            digest,
            size,
            _identity(module_id, version).as_posix(),
            self.public_url(module_id, version),
        )

    def _verify_at(
        self, parent: int, module_id: str, version: str, expected_sha256: str
    ) -> StoredArtifact:
        name = _identity(module_id, version, expected_sha256).name
        with _regular_file(parent, name) as stream:
            actual, size = _digest(stream)
        if actual != expected_sha256:
            raise ArtifactConflict("Existing artifact SHA-256 mismatch; refusing overwrite")
        return self._metadata(module_id, version, actual, size)

    def exists(self, module_id: str, version: str) -> bool:
        relative = _identity(module_id, version)
        try:
            with (
                _directory(self.root / relative.parent) as parent,
                _regular_file(parent, relative.name),
            ):
                return True
        except FileNotFoundError:
            return False
        except OSError:
            raise ArtifactStoreError("Unable to inspect artifact storage") from None

    def verify(self, module_id: str, version: str, expected_sha256: str) -> StoredArtifact:
        relative = _identity(module_id, version, expected_sha256)
        try:
            with _directory(self.root / relative.parent) as parent:
                return self._verify_at(parent, module_id, version, expected_sha256)
        except FileNotFoundError:
            raise ArtifactNotFound("Artifact is not stored") from None
        except OSError:
            raise ArtifactStoreError("Unable to verify stored artifact") from None

    @contextmanager
    def _staging(self) -> Iterator[int]:
        with _directory(self.root / ".staging", create=True, mode=0o700) as staging:
            metadata = os.fstat(staging)
            if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise InvalidArtifact("Staging must be private to the trusted publisher (0700)")
            yield staging

    def _check_parent(self, relative: Path, parent: int) -> None:
        # Detect a directory replaced since it was opened; all access remains no-follow.
        with _directory(self.root / relative.parent) as current:
            left, right = os.fstat(parent), os.fstat(current)
            if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino):
                raise InvalidArtifact("Artifact directory changed during publication")
        if not (self.root / relative).resolve().is_relative_to(self.root.resolve()):
            raise InvalidArtifact("Artifact target escapes the configured root")

    def publish(
        self, module_id: str, version: str, source: Path, expected_sha256: str
    ) -> Publication:
        relative = _identity(module_id, version, expected_sha256)
        source = _safe_absolute(source)
        try:
            with (
                _directory(source.parent) as source_parent,
                _regular_file(source_parent, source.name) as stream,
            ):
                actual, _ = _digest(stream)
                if actual != expected_sha256:
                    raise InvalidArtifact("Source SHA-256 does not match expected digest")
                return self._publish_verified(module_id, version, relative, stream, expected_sha256)
        except FileNotFoundError:
            raise InvalidArtifact("Source or storage directory is missing") from None
        except OSError:
            raise ArtifactStoreError(
                "Artifact storage operation failed; verify before retry"
            ) from None

    def _publish_verified(
        self, module_id: str, version: str, relative: Path, source: BinaryIO, expected: str
    ) -> Publication:
        with _directory(self.root / relative.parent, create=True) as parent:
            try:
                artifact = self._verify_at(parent, module_id, version, expected)
            except FileNotFoundError:
                pass
            else:
                # Complete durability after a previous caller lost a post-link response.
                with _regular_file(parent, relative.name) as stored:
                    os.fsync(stored.fileno())
                os.fsync(parent)
                return Publication(artifact, STATUS_ALREADY_PRESENT)
            with self._staging() as staging:
                if os.fstat(parent).st_dev != os.fstat(staging).st_dev:
                    raise ArtifactStoreError("Staging and final path must share a filesystem")
                temporary = f"{uuid4().hex}.partial"
                descriptor = os.open(
                    temporary,
                    os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=staging,
                )
                try:
                    with os.fdopen(descriptor, "w+b") as output:
                        source.seek(0)
                        shutil.copyfileobj(source, output, 1024 * 1024)
                        output.flush()
                        os.fchmod(output.fileno(), FILE_MODE)
                        os.fsync(output.fileno())
                        digest, _ = _digest(output)
                        if digest != expected:
                            raise InvalidArtifact("Copied artifact SHA-256 mismatch")
                        self._check_parent(relative, parent)
                        try:
                            os.link(
                                temporary,
                                relative.name,
                                src_dir_fd=staging,
                                dst_dir_fd=parent,
                                follow_symlinks=False,
                            )
                            status = STATUS_PUBLISHED
                        except FileExistsError:
                            status = STATUS_ALREADY_PRESENT
                        # Verify complete final bytes even when another publisher won.
                        artifact = self._verify_at(parent, module_id, version, expected)
                        os.fsync(parent)
                        return Publication(artifact, status)
                finally:
                    os.unlink(temporary, dir_fd=staging)
                    os.fsync(staging)

    def health(self, *, publisher: bool = False) -> dict[str, bool | str]:
        """Read mode never creates a root; publisher mode tests private staging writes."""
        try:
            with _directory(self.root) as root:
                os.listdir(root)
                if publisher:
                    with self._staging() as staging:
                        if os.fstat(root).st_dev != os.fstat(staging).st_dev:
                            raise ArtifactStoreError("Staging must share the root filesystem")
                        name = f"{uuid4().hex}.health"
                        descriptor = os.open(
                            name,
                            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                            0o600,
                            dir_fd=staging,
                        )
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                            os.unlink(name, dir_fd=staging)
                            os.fsync(staging)
            return {
                "readable": True,
                "publisher_writable": publisher,
                "mode": "publisher" if publisher else "reader",
            }
        except OSError:
            raise ArtifactStoreError("Artifact storage health check failed") from None
