"""Trusted local-file publisher; never approves candidates or writes Registry metadata."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from scripts.artifact_store import (
    ArtifactConflict,
    ArtifactStoreError,
    FilesystemArtifactStore,
    InvalidArtifact,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        help="Absolute storage root; defaults to PACKAGES_REGISTRY_ARTIFACT_ROOT",
    )
    args = parser.parse_args()
    try:
        store = (
            FilesystemArtifactStore(args.artifact_root)
            if args.artifact_root is not None
            else FilesystemArtifactStore.from_environment()
        )
        result = store.publish(args.module, args.version, args.source, args.expected_sha256)
        print(json.dumps({"status": result.status, **asdict(result.artifact)}, sort_keys=True))
        return 0
    except ArtifactConflict:
        status, code = "conflict", 3
    except InvalidArtifact:
        status, code = "invalid", 2
    except ArtifactStoreError:
        status, code = "storage-error", 4
    print(json.dumps({"status": status}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
