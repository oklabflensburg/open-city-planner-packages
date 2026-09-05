import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "roles/packages_registry/files/prune_releases.py"
spec = importlib.util.spec_from_file_location("prune_releases", SCRIPT)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "releases"
    root.mkdir()
    releases = []
    for number in range(8):
        release = root / f"{number:040x}"
        release.mkdir()
        (release / ".release-ready").write_text(release.name + "\n")
        (release / "node_modules").mkdir()
        (release / "node_modules/file").write_text("data")
        os.utime(release, (number, number))
        releases.append(release)
    (tmp_path / "current").symlink_to(releases[0])
    (tmp_path / "previous").symlink_to(releases[1])
    return root, releases


def test_current_previous_and_newest_retention(tree):
    root, releases = tree
    assert cleanup.select_releases(root, 5) == releases[2:5][::-1]
    cleanup.prune(root, 5)
    assert {path for path in releases if path.exists()} == set(releases[:2] + releases[5:])
    assert cleanup.prune(root, 5) == []


@pytest.mark.parametrize("invalid", ["not-a-sha", "a" * 39, "A" * 40, "artifacts", "repo"])
def test_invalid_directory_refuses_entire_cleanup(tree, invalid):
    root, releases = tree
    (root / invalid).mkdir()
    with pytest.raises(ValueError, match="Unsafe release"):
        cleanup.prune(root, 5)
    assert all(path.exists() for path in releases)


def test_symlink_candidate_refused(tree, tmp_path):
    root, releases = tree
    (root / ("f" * 40)).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe release"):
        cleanup.prune(root, 5)
    assert all(path.exists() for path in releases)


def test_outside_protection_target_refused(tree, tmp_path):
    root, releases = tree
    (tmp_path / "current").unlink()
    (tmp_path / "current").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="Unsafe release"):
        cleanup.prune(root, 5)
    assert all(path.exists() for path in releases)


def test_artifact_store_and_nested_symlink_untouched(tree, tmp_path):
    root, releases = tree
    artifacts = tmp_path / "artifacts/modules"
    artifacts.mkdir(parents=True)
    artifact = artifacts / "immutable.ocp"
    artifact.write_bytes(b"immutable")
    (releases[2] / "artifact-link").symlink_to(artifacts, target_is_directory=True)
    cleanup.prune(root, 5)
    assert artifact.read_bytes() == b"immutable"
    with pytest.raises(ValueError, match="Unsafe release root"):
        cleanup.prune(artifacts, 5)


def test_symlink_release_root_refused(tree, tmp_path):
    root, _ = tree
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe release root"):
        cleanup.prune(alias / root.name, 5)


def test_unclassified_and_missing_previous_refused(tree, tmp_path):
    root, releases = tree
    (releases[2] / ".release-ready").unlink()
    with pytest.raises(ValueError, match="Unclassified"):
        cleanup.prune(root, 5)
    (tmp_path / "previous").unlink()
    with pytest.raises(ValueError, match="protection pointer"):
        cleanup.prune(root, 5)


def test_mount_refused_before_any_delete(tree, monkeypatch):
    root, releases = tree
    monkeypatch.setattr(
        cleanup.os.path, "ismount", lambda path: path == releases[2] / "node_modules"
    )
    with pytest.raises(ValueError, match="Mounted directory"):
        cleanup.prune(root, 5)
    assert all(path.exists() for path in releases)


def test_mismatched_ready_marker_refused(tree):
    root, releases = tree
    (releases[2] / ".release-ready").write_text("wrong commit")
    with pytest.raises(ValueError, match="mismatched ready marker"):
        cleanup.prune(root, 5)
    assert all(path.exists() for path in releases)


def test_delete_failure_is_reported(tree, tmp_path, monkeypatch, capsys):
    root, _ = tree
    monkeypatch.setattr(cleanup, "LOCK", tmp_path / "lock")
    monkeypatch.setattr("sys.argv", ["cleanup", "--release-root", str(root), "--retention", "5"])

    def fail_delete(path):
        raise OSError(f"deletion failed: {path}")

    fail_delete.avoids_symlink_attacks = True
    monkeypatch.setattr(cleanup.shutil, "rmtree", fail_delete)
    assert cleanup.main() == 1
    assert "deletion failed" in capsys.readouterr().err


def test_cli_lock_and_failure_reporting(tree, tmp_path, monkeypatch, capsys):
    root, _ = tree
    lock = tmp_path / "lock"
    monkeypatch.setattr(cleanup, "LOCK", lock)
    monkeypatch.setattr("sys.argv", ["cleanup", "--release-root", str(root), "--retention", "5"])
    lock.mkdir()
    assert cleanup.main() == 0
    assert "deferred" in capsys.readouterr().out
    lock.rmdir()
    (root / "unsafe").mkdir()
    assert cleanup.main() == 1
    assert "failed" in capsys.readouterr().err
    assert not lock.exists()


def test_published_store_survives_real_application_pruning(tree, tmp_path):
    import hashlib

    from scripts.artifact_store import FilesystemArtifactStore

    release_root, releases = tree
    source = tmp_path / "reviewed.ocp"
    source.write_bytes(b"reviewed bytes")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    before = store.publish("statistics", "0.4.0", source, digest).artifact
    assert cleanup.prune(release_root, 5)
    assert store.verify("statistics", "0.4.0", digest) == before
    assert len([r for r in releases if r.exists()]) == 5
