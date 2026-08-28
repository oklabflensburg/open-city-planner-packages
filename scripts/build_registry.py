#!/usr/bin/env python3
"""Build the complete deterministic static registry deployment directory."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

if __package__:
    from .registry import (
        RegistryValidationError,
        build_index,
        canonical_json,
        canonical_module,
        load_registry,
    )
else:
    from registry import (
        RegistryValidationError,
        build_index,
        canonical_json,
        canonical_module,
        load_registry,
    )

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build(registry_root: Path, output: Path) -> None:
    modules = load_registry(registry_root)
    resolved_output = output.resolve()
    forbidden = {Path("/").resolve(), REPOSITORY_ROOT.resolve(), registry_root.resolve()}
    unsafe_tree = REPOSITORY_ROOT.resolve().is_relative_to(
        resolved_output
    ) or resolved_output.is_relative_to(registry_root.resolve())
    if resolved_output in forbidden or unsafe_tree or output.is_symlink():
        raise RegistryValidationError(f"refusing unsafe output directory: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    backup: Path | None = None
    try:
        (staging / "modules").mkdir()
        (staging / "index.json").write_text(
            canonical_json(build_index(modules)), encoding="utf-8", newline="\n"
        )
        for module in modules:
            (staging / "modules" / f'{module["id"]}.json').write_text(
                canonical_json(canonical_module(module)), encoding="utf-8", newline="\n"
            )
        if output.exists():
            backup = Path(
                tempfile.mkdtemp(prefix=f".{output.name}.previous.", dir=output.parent)
            )
            backup.rmdir()
            os.replace(output, backup)
        os.replace(staging, output)
        if backup is not None and backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if backup is not None and not output.exists() and backup.exists():
            os.replace(backup, output)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REPOSITORY_ROOT / "registry")
    parser.add_argument("--output", type=Path, default=REPOSITORY_ROOT / "dist")
    args = parser.parse_args()
    try:
        build(args.registry, args.output)
    except (OSError, RegistryValidationError) as exc:
        print(f"registry build failed: {exc}", file=sys.stderr)
        return 1
    print(f"registry built at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
