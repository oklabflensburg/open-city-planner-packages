"""Render a review-safe Markdown summary for a validated build candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.registry_candidate import validate_candidate


def render(value: dict) -> str:
    modules = value["requires"].get("modules", {})
    dependencies = ", ".join(f"{key} {constraint}" for key, constraint in modules.items())
    return f"""Closes #35
Part of #36

Central OCP builder candidate (human review required; no auto-merge).

| Field | Value |
| --- | --- |
| Module | `{value["module_id"]}` |
| Version | `{value["version"]}` |
| Source repository | `{value["source_repository"]}` |
| Source tag | `{value["source_tag"]}` |
| Source commit | `{value["source_commit"]}` |
| Builder | `ocp-builder v{value["builder_version"]}` |
| Builder commit | `{value["builder_commit"]}` |
| Bundle SHA-256 | `{value["bundle_sha256"]}` |
| Reproducibility | `{value["reproducible"]}` |
| Host contract | `{value["host_contract"]}` |
| Host compatibility | `{value["requires"].get("host", "")}` |
| SDK compatibility | `{value["requires"].get("sdk", "")}` |
| Module dependencies | `{dependencies or "none"}` |
| Planned channel | `{value["planned_channel"]}` |
| Candidate artifact | `{value["artifact_candidate"]}` |

The `.ocp`, checksum, and provenance are retained as a GitHub Actions candidate artifact.
Merging this PR does not auto-promote or directly mutate the production Registry.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provenance", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = validate_candidate(json.loads(args.provenance.read_text(encoding="utf-8")))
    args.output.write_text(render(value), encoding="utf-8")
    print(f"module_id={value['module_id']}")
    print(f"version={value['version']}")


if __name__ == "__main__":
    main()
