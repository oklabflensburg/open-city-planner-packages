#!/usr/bin/env python3
"""Validate Registry v1 source and, optionally, immutable published history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__:
    from .registry import (
        RegistryValidationError,
        load_registry,
        load_registry_from_git,
        validate_immutability,
    )
else:
    from registry import (
        RegistryValidationError,
        load_registry,
        load_registry_from_git,
        validate_immutability,
    )

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=REPOSITORY_ROOT / "registry", help="source directory"
    )
    parser.add_argument(
        "--base-ref", help="Git reference whose published id/version entries must remain immutable"
    )
    args = parser.parse_args()
    try:
        modules = load_registry(args.registry)
        if args.base_ref:
            base_modules = load_registry_from_git(args.base_ref, REPOSITORY_ROOT)
            validate_immutability(modules, base_modules)
    except (OSError, RegistryValidationError) as exc:
        print(f"registry validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"registry valid: schema v1, {len(modules)} module(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
