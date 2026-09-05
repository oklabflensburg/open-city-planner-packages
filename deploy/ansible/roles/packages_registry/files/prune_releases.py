#!/usr/bin/python3
"""Local release retention only. Shared by systemd and manual maintenance."""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

LOCK = Path("/var/lib/ocp-packages-maintenance/lock")
SHA = re.compile(r"[0-9a-f]{40}")


def release_path(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if (
        path.is_symlink()
        or resolved != path
        or resolved.parent != root
        or not SHA.fullmatch(path.name)
        or not path.is_dir()
        or os.path.ismount(path)
    ):
        raise ValueError(f"Unsafe release path: {path}")
    return resolved


def protected_paths(root: Path) -> set[Path]:
    protected = set()
    for name in ("current", "previous"):
        link = root.parent / name
        if not link.is_symlink():
            raise ValueError(f"Missing or non-symlink protection pointer: {link}")
        target = link.resolve(strict=True)
        protected.add(release_path(target, root))
    return protected


def select_releases(root: Path, retention: int) -> list[Path]:
    # Fixed sibling layout prevents pointing this command at repo/ or artifacts/.
    if (
        not root.is_absolute()
        or root.name != "releases"
        or root.parent == Path("/")
        or root.resolve(strict=True) != root
        or not root.is_dir()
        or retention < 2
    ):
        raise ValueError(f"Unsafe release root or retention: {root}, {retention}")
    protected = protected_paths(root)
    releases = []
    # Classify the entire set before deleting anything; never silently skip anomalies.
    for entry in root.iterdir():
        release_path(entry, root)
        marker = entry / ".release-ready"
        if marker.is_symlink() or not marker.is_file():
            raise ValueError(f"Unclassified release without regular ready marker: {entry}")
        if marker.read_text().strip() != entry.name:
            raise ValueError(f"Unclassified release with mismatched ready marker: {entry}")
        if entry not in protected:
            releases.append(entry)
    releases.sort(key=lambda path: (-path.stat().st_mtime_ns, path.name))
    return releases[max(0, retention - len(protected)) :]


def prune(root: Path, retention: int) -> list[str]:
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError("Safe fd-based recursive removal is required")
    selected = select_releases(root, retention)
    # Reject nested mounts before any deletion; symlinks inside a release are unlinked,
    # never followed (pnpm uses them extensively).
    for path in selected:
        for directory, dirs, _files in os.walk(path, followlinks=False):
            for name in dirs:
                child = Path(directory) / name
                if not child.is_symlink() and os.path.ismount(child):
                    raise ValueError(f"Mounted directory inside release: {child}")
    deleted = []
    for path in selected:
        release_path(path, root)
        if path in protected_paths(root):
            raise ValueError(f"Release became protected: {path}")
        print(f"Pruning inactive release {path}", flush=True)
        shutil.rmtree(path)
        deleted.append(str(path))
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", required=True, type=Path)
    parser.add_argument("--retention", required=True, type=int)
    args = parser.parse_args()
    try:
        LOCK.mkdir(mode=0o700)
    except FileExistsError:
        print("Deployment/maintenance lock exists; cleanup deferred.", flush=True)
        return 0
    try:
        print(json.dumps({"deleted": prune(args.release_root, args.retention)}))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Cleanup refused/failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        LOCK.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
