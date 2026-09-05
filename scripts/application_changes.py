"""Classify exact push changes without suppressing PR validation or security checks."""

import argparse
import re
import subprocess

RUNTIME_PREFIXES = ("web/", "deploy/", "scripts/", "schema/", "config/")
RUNTIME_FILES = {
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".node-version",
    ".github/workflows/registry.yml",
}


def application_deploy_required(paths):
    return any(path in RUNTIME_FILES or path.startswith(RUNTIME_PREFIXES) for path in paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in (args.before, args.after)):
        raise ValueError("Expected full commit SHAs")
    if args.before == "0" * 40:
        print("deploy=true")
        return
    # --no-renames accounts for both old and new paths of a renamed runtime file.
    result = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "-z", args.before, args.after],
        check=True,
        capture_output=True,
    )
    paths = result.stdout.decode().split("\0")
    print("deploy=" + str(application_deploy_required(paths)).lower())


if __name__ == "__main__":
    main()
