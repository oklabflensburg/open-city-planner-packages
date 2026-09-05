"""Filesystem storage safety, process races, failure recovery and CLI contracts."""

import errno
import hashlib
import json
import multiprocessing
import os
import shutil
import stat
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from scripts import artifact_store
from scripts.artifact_store import (
    ArtifactConflict,
    ArtifactNotFound,
    ArtifactStoreError,
    FilesystemArtifactStore,
    InvalidArtifact,
)

MODULE = "statistics"
VERSION = "0.4.0"
PAYLOAD = b"reviewed fixture bytes, not the real Statistics candidate"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
KEY = "modules/statistics/0.4.0/statistics-0.4.0.ocp"


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "untrusted-name.bin"
    path.write_bytes(PAYLOAD)
    return path


@pytest.fixture
def store(tmp_path):
    return FilesystemArtifactStore(tmp_path / "artifacts")


def test_publish_verify_idempotency_and_metadata(store, source):
    assert not store.exists(MODULE, VERSION)
    with pytest.raises(ArtifactNotFound):
        store.verify(MODULE, VERSION, DIGEST)
    result = store.publish(MODULE, VERSION, source, DIGEST)
    target = store.root / KEY
    before = target.stat()
    assert result.status == "published"
    assert result.artifact.digest == DIGEST
    assert result.artifact.digest_algorithm == "sha256"
    assert result.artifact.byte_size == len(PAYLOAD)
    assert result.artifact.storage_locator == KEY
    assert result.artifact.public_url == f"https://packages.stadtplaner.oklabflensburg.de/{KEY}"
    assert target.read_bytes() == PAYLOAD
    assert stat.S_IMODE(before.st_mode) == 0o644
    assert before.st_nlink == 1  # No persistent staging/source hardlink remains.
    assert not list((store.root / ".staging").iterdir())
    assert store.publish(MODULE, VERSION, source, DIGEST).status == "already-present"
    assert store.verify(MODULE, VERSION, DIGEST) == result.artifact
    assert store.exists(MODULE, VERSION)
    assert target.stat().st_ino == before.st_ino
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    assert source.stat().st_ino != before.st_ino


def test_source_mismatch_fails_before_storage_write(store, source):
    with pytest.raises(InvalidArtifact, match="Source SHA"):
        store.publish(MODULE, VERSION, source, "0" * 64)
    assert not store.root.exists()


def test_conflict_and_corrupt_stored_bytes_are_never_replaced(store, source):
    store.publish(MODULE, VERSION, source, DIGEST)
    source.write_bytes(b"different")
    with pytest.raises(ArtifactConflict, match="refusing overwrite"):
        store.publish(MODULE, VERSION, source, hashlib.sha256(b"different").hexdigest())
    assert (store.root / KEY).read_bytes() == PAYLOAD
    (store.root / KEY).write_bytes(b"corrupt")
    source.write_bytes(PAYLOAD)
    with pytest.raises(ArtifactConflict):
        store.publish(MODULE, VERSION, source, DIGEST)
    with pytest.raises(ArtifactConflict):
        store.verify(MODULE, VERSION, DIGEST)
    assert (store.root / KEY).read_bytes() == b"corrupt"


@pytest.mark.parametrize(
    "module,version",
    [
        ("../outside", VERSION),
        ("a/b", VERSION),
        ("a\\b", VERSION),
        ("a\x00b", VERSION),
        ("%2e%2e", VERSION),
        (MODULE, "../0.4.0"),
        (MODULE, "0.4.0/elsewhere"),
        (MODULE, "0.4.0\\elsewhere"),
        (MODULE, "0.4.0\x00"),
        (MODULE, "latest"),
        (MODULE, "v0.4.0"),
        (MODULE, "%2e%2e"),
    ],
)
def test_invalid_identity_rejected_before_io(store, source, module, version):
    with pytest.raises(InvalidArtifact):
        store.publish(module, version, source, DIGEST)
    assert not store.root.exists()


@pytest.mark.parametrize("digest", [None, "", "0" * 63, "A" * 64, "sha256:" + DIGEST])
def test_invalid_digest_rejected_before_io(store, source, digest):
    with pytest.raises(InvalidArtifact):
        store.publish(MODULE, VERSION, source, digest)
    assert not store.root.exists()


@pytest.mark.parametrize("part", ["root", "ancestor", "modules", "version", "final", "staging"])
def test_symlink_targets_fail_closed(store, source, tmp_path, part):
    outside = tmp_path / "outside"
    outside.mkdir()
    if part == "root":
        store.root.symlink_to(outside, target_is_directory=True)
    elif part == "ancestor":
        (tmp_path / "alias").symlink_to(outside, target_is_directory=True)
        store = FilesystemArtifactStore(tmp_path / "alias/artifacts")
    else:
        key = {
            "modules": "modules",
            "version": "modules/statistics/0.4.0",
            "final": KEY,
            "staging": ".staging",
        }[part]
        target = store.root / key
        target.parent.mkdir(parents=True)
        target.symlink_to(
            source if part == "final" else outside, target_is_directory=part != "final"
        )
    with pytest.raises(InvalidArtifact):
        store.publish(MODULE, VERSION, source, DIGEST)
    assert not list(outside.iterdir())
    assert source.read_bytes() == PAYLOAD


@pytest.mark.parametrize("kind", ["symlink", "ancestor", "fifo", "directory", "missing"])
def test_source_must_be_regular_and_no_follow(store, source, tmp_path, kind):
    invalid = tmp_path / "invalid"
    if kind == "symlink":
        invalid.symlink_to(source)
    elif kind == "ancestor":
        invalid.symlink_to(tmp_path, target_is_directory=True)
        invalid = invalid / source.name
    elif kind == "fifo":
        os.mkfifo(invalid)
    elif kind == "directory":
        invalid.mkdir()
    with pytest.raises(InvalidArtifact):
        store.publish(MODULE, VERSION, invalid, DIGEST)
    assert not store.root.exists()


@pytest.mark.parametrize("kind", ["fifo", "directory"])
def test_existing_nonregular_final_rejected(store, source, kind):
    target = store.root / KEY
    target.parent.mkdir(parents=True)
    if kind == "fifo":
        os.mkfifo(target)
    else:
        target.mkdir()
    with pytest.raises(InvalidArtifact):
        store.publish(MODULE, VERSION, source, DIGEST)


def test_copy_corruption_is_detected_before_link(store, source, monkeypatch):
    def corrupt_copy(src, dest, length):
        dest.write(b"corrupted during copy")

    monkeypatch.setattr(artifact_store.shutil, "copyfileobj", corrupt_copy)
    with pytest.raises(InvalidArtifact, match="Copied artifact"):
        store.publish(MODULE, VERSION, source, DIGEST)
    assert not (store.root / KEY).exists()
    assert not list((store.root / ".staging").iterdir())


@pytest.mark.parametrize("failure", ["copy", "fsync", "link", "cross-device"])
def test_failure_before_publication_leaves_no_final(store, source, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise OSError(errno.EXDEV if failure == "cross-device" else errno.EIO, "private path")

    if failure == "copy":
        monkeypatch.setattr(artifact_store.shutil, "copyfileobj", fail)
    elif failure == "fsync":
        original = artifact_store.os.fsync

        def fail_file(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                fail()
            return original(fd)

        monkeypatch.setattr(artifact_store.os, "fsync", fail_file)
    else:
        monkeypatch.setattr(artifact_store.os, "link", fail)
    with pytest.raises(ArtifactStoreError) as error:
        store.publish(MODULE, VERSION, source, DIGEST)
    assert "private path" not in str(error.value)
    assert not (store.root / KEY).exists()
    assert not list((store.root / ".staging").iterdir())


def test_post_link_failure_keeps_verified_bytes_and_retry_recovers(store, source, monkeypatch):
    original = artifact_store.os.fsync
    target = store.root / KEY

    def fail_after_link(fd):
        if target.exists() and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("simulated durability failure")
        return original(fd)

    with monkeypatch.context() as patch:
        patch.setattr(artifact_store.os, "fsync", fail_after_link)
        with pytest.raises(ArtifactStoreError):
            store.publish(MODULE, VERSION, source, DIGEST)
    assert target.read_bytes() == PAYLOAD
    assert store.publish(MODULE, VERSION, source, DIGEST).status == "already-present"


def test_atomic_link_sees_synced_complete_same_filesystem_copy(store, source, monkeypatch):
    original_link = artifact_store.os.link
    original_sync = artifact_store.os.fsync
    synced = set()

    def record_sync(fd):
        original_sync(fd)
        metadata = os.fstat(fd)
        synced.add((metadata.st_dev, metadata.st_ino))

    def inspect_link(src, dst, *, src_dir_fd, dst_dir_fd, follow_symlinks):
        assert not (store.root / KEY).exists()
        src_stat = os.stat(src, dir_fd=src_dir_fd, follow_symlinks=False)
        assert (src_stat.st_dev, src_stat.st_ino) in synced
        assert src_stat.st_dev == os.fstat(dst_dir_fd).st_dev
        assert src_stat.st_size == len(PAYLOAD)
        assert not follow_symlinks
        return original_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )

    monkeypatch.setattr(artifact_store.os, "fsync", record_sync)
    monkeypatch.setattr(artifact_store.os, "link", inspect_link)
    store.publish(MODULE, VERSION, source, DIGEST)
    metadata = (store.root / KEY).parent.stat()
    assert (metadata.st_dev, metadata.st_ino) in synced


def test_parent_symlink_swap_during_copy_never_writes_outside(store, source, tmp_path, monkeypatch):
    original = artifact_store.shutil.copyfileobj
    outside = tmp_path / "outside"
    outside.mkdir()

    def swap(src, dest, length):
        original(src, dest, length)
        parent = (store.root / KEY).parent
        parent.rename(parent.with_name("moved"))
        parent.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(artifact_store.shutil, "copyfileobj", swap)
    with pytest.raises(InvalidArtifact):
        store.publish(MODULE, VERSION, source, DIGEST)
    assert not list(outside.iterdir())
    assert not list((store.root / ".staging").iterdir())


def _racing_publish(root, source, digest, barrier):
    # Separate processes must both reach publication before either can win.
    original = artifact_store.os.link

    def synchronize(*args, **kwargs):
        barrier.wait(timeout=15)
        return original(*args, **kwargs)

    artifact_store.os.link = synchronize
    try:
        try:
            return (
                FilesystemArtifactStore(Path(root))
                .publish(MODULE, VERSION, Path(source), digest)
                .status
            )
        except ArtifactConflict:
            return "conflict"
    finally:
        artifact_store.os.link = original


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_processes_never_clobber(store, source, tmp_path, conflicting):
    second = tmp_path / "second"
    second.write_bytes(b"another candidate" if conflicting else PAYLOAD)
    second_digest = hashlib.sha256(second.read_bytes()).hexdigest()
    context = multiprocessing.get_context("spawn")
    with (
        context.Manager() as manager,
        ProcessPoolExecutor(max_workers=2, mp_context=context) as pool,
    ):
        barrier = manager.Barrier(2)
        a = pool.submit(_racing_publish, str(store.root), str(source), DIGEST, barrier)
        b = pool.submit(_racing_publish, str(store.root), str(second), second_digest, barrier)
        assert sorted([a.result(timeout=25), b.result(timeout=25)]) == sorted(
            [
                "published",
                "conflict" if conflicting else "already-present",
            ]
        )
    actual = hashlib.sha256((store.root / KEY).read_bytes()).hexdigest()
    assert actual in {DIGEST, second_digest}
    store.verify(MODULE, VERSION, actual)
    assert not list((store.root / ".staging").iterdir())


def test_backup_restore_preserves_url_and_verifies_digest(store, source, tmp_path):
    expected = store.publish(MODULE, VERSION, source, DIGEST).artifact
    shutil.copytree(store.root / "modules", tmp_path / "restored/modules")
    restored = FilesystemArtifactStore(tmp_path / "restored")
    assert restored.verify(MODULE, VERSION, DIGEST) == expected
    (restored.root / KEY).write_bytes(b"damaged backup")
    with pytest.raises(ArtifactConflict):
        restored.verify(MODULE, VERSION, DIGEST)


def test_health_modes_and_environment(store, monkeypatch):
    with pytest.raises(ArtifactStoreError):
        store.health()
    assert not store.root.exists()
    store.root.mkdir()
    before = list(store.root.iterdir())
    assert store.health() == {"readable": True, "publisher_writable": False, "mode": "reader"}
    assert list(store.root.iterdir()) == before
    assert store.health(publisher=True)["publisher_writable"]
    assert not list((store.root / ".staging").iterdir())
    monkeypatch.setenv("PACKAGES_REGISTRY_ARTIFACT_ROOT", str(store.root))
    assert FilesystemArtifactStore.from_environment().root == store.root
    monkeypatch.delenv("PACKAGES_REGISTRY_ARTIFACT_ROOT")
    with pytest.raises(InvalidArtifact):
        FilesystemArtifactStore.from_environment()


@pytest.mark.parametrize(
    "root",
    [
        "relative",
        "/",
        "/tmp/releases/abc/artifacts",
        "/tmp/current/artifacts",
        "/tmp/../escape",
        "/tmp/bad\x00root",
    ],
)
def test_unsafe_root_rejected(root):
    with pytest.raises(InvalidArtifact):
        FilesystemArtifactStore(Path(root))


def test_cli_statuses_and_no_path_leak(store, source):
    args = [
        sys.executable,
        "-m",
        "scripts.publish_artifact",
        "--module",
        MODULE,
        "--version",
        VERSION,
        "--source",
        str(source),
        "--expected-sha256",
        DIGEST,
        "--artifact-root",
        str(store.root),
    ]

    def run(arguments):
        return subprocess.run(arguments, capture_output=True, text=True, check=False)

    for status in ("published", "already-present"):
        result = run(args)
        assert result.returncode == 0 and json.loads(result.stdout)["status"] == status
        assert str(store.root) not in result.stdout + result.stderr
    source.write_bytes(b"different")
    result = run(args)
    assert result.returncode == 2 and json.loads(result.stdout) == {"status": "invalid"}
    args[args.index(DIGEST)] = hashlib.sha256(b"different").hexdigest()
    result = run(args)
    assert result.returncode == 3 and json.loads(result.stdout) == {"status": "conflict"}
    assert str(source) not in result.stdout + result.stderr


def test_cli_storage_error_is_sanitized(store, source, monkeypatch, capsys):
    from scripts import publish_artifact

    def fail(*args, **kwargs):
        raise ArtifactStoreError("private filesystem path")

    monkeypatch.setattr(FilesystemArtifactStore, "publish", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish-artifact",
            "--module",
            MODULE,
            "--version",
            VERSION,
            "--source",
            str(source),
            "--expected-sha256",
            DIGEST,
            "--artifact-root",
            str(store.root),
        ],
    )
    assert publish_artifact.main() == 4
    assert json.loads(capsys.readouterr().out) == {"status": "storage-error"}


def test_final_digest_is_rechecked_after_link(store, source, monkeypatch):
    original = artifact_store.os.link

    def corrupt_after_link(*args, **kwargs):
        original(*args, **kwargs)
        (store.root / KEY).write_bytes(b"external corruption after publication")

    monkeypatch.setattr(artifact_store.os, "link", corrupt_after_link)
    with pytest.raises(ArtifactConflict):
        store.publish(MODULE, VERSION, source, DIGEST)
    assert (store.root / KEY).read_bytes() == b"external corruption after publication"
    assert not list((store.root / ".staging").iterdir())


def test_staging_must_remain_private(store, source):
    (store.root / ".staging").mkdir(parents=True)
    (store.root / ".staging").chmod(0o755)
    with pytest.raises(InvalidArtifact, match="private"):
        store.publish(MODULE, VERSION, source, DIGEST)
    assert not (store.root / KEY).exists()
