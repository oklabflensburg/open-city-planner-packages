#!/usr/bin/python3
"""One persistent flock authority for deployment and local release retention."""

import argparse
import fcntl
import os
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

LOCK = Path("/var/lib/ocp-packages-maintenance/maintenance.lock")
BUSY = 75


class LockBusy(Exception):
    """Another maintenance process owns the file lock."""


@contextmanager
def exclusive_lock(path: Path = LOCK):
    # Never unlink/replace this file: a second inode would create a second lock.
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"Maintenance lock is not a regular file: {path}")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockBusy(str(path)) from exc
        yield fd
    finally:
        # Closing (including on process death) releases the kernel lock. Do not
        # LOCK_UN here: the command may have inherited this open file description.
        os.close(fd)


def check_legacy_cleanup() -> None:
    """After atomic entry-point replacement, refuse still-running old cleanup.

    Newly started cleanup now uses flock. Existing processes may still execute
    the old mkdir implementation. Conservatively reject any other prune process;
    do not kill maintenance or infer ownership from the old directory's age.
    """
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        if any(
            Path(os.fsdecode(arg)).name in {"ocp-packages-prune-releases", "prune_releases.py"}
            for arg in args
            if arg
        ):
            raise RuntimeError(
                f"Cleanup process {entry.name} is still running; retry after it exits "
                "(it may predate the flock migration)."
            )


def run(command: list[str], path: Path = LOCK) -> int:
    try:
        with exclusive_lock(path) as fd:
            environment = dict(os.environ, OCP_MAINTENANCE_LOCK_HELD="1")
            # The parent retains the lock while Ansible runs all tasks/rescue.
            # Also pass it to Ansible so killing just this supervisor does not
            # unlock a deployment that is still running.
            return subprocess.run(command, env=environment, pass_fds=(fd,), check=False).returncode
    except LockBusy:
        print("Deployment/maintenance lock busy; deployment refused. Retry later.", file=sys.stderr)
        return BUSY
    except (OSError, ValueError) as exc:
        print(f"Maintenance lock/command failed: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-legacy-cleanup", action="store_true")
    parser.add_argument("--run", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.check_legacy_cleanup:
        try:
            check_legacy_cleanup()
        except (OSError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    if not args.run:
        parser.error("--run requires a command")
    return run(args.run)


if __name__ == "__main__":
    sys.exit(main())
