"""Validate and persist review metadata emitted by ocp-builder v1."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts.artifact_store import canonical_public_artifact_url
from scripts.ocp_builder import COMMIT_RE, load_policies
from scripts.registry import SEMVER_RE, SHA256_RE, canonical_json

REQUIRED = {
    "schema_version",
    "module_id",
    "version",
    "classification",
    "source_repository",
    "source_tag",
    "source_commit",
    "builder_version",
    "builder_commit",
    "bundle_format_version",
    "bundle_sha256",
    "artifact_candidate",
    "reproducible",
    "host_contract",
    "planned_channel",
    "requires",
    "registry_status",
}
VERSION_RE = SEMVER_RE


def validate_candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"build_environment"} != REQUIRED:
        raise ValueError("candidate has unknown or missing fields")
    _, policies = load_policies()
    module_id = value["module_id"]
    policy = policies.get(module_id)
    if policy is None:
        raise ValueError("candidate module is not allowlisted")
    if value["source_repository"] != policy.source_url:
        raise ValueError("candidate source repository does not match allowlist")
    if value["classification"] != "first-party":
        raise ValueError("candidate classification is not first-party")
    if value["schema_version"] != 1 or value["builder_version"] != 1:
        raise ValueError("unsupported candidate or builder version")
    if value["bundle_format_version"] != 1:
        raise ValueError("unsupported bundle format")
    if not VERSION_RE.fullmatch(value["version"]):
        raise ValueError("invalid candidate version")
    if value["source_tag"] != f"v{value['version']}":
        raise ValueError("candidate tag/version mismatch")
    if not COMMIT_RE.fullmatch(value["source_commit"]):
        raise ValueError("invalid source commit")
    builder_commit = value["builder_commit"]
    if builder_commit != "unknown" and not COMMIT_RE.fullmatch(builder_commit):
        raise ValueError("invalid builder commit")
    if not SHA256_RE.fullmatch(value["bundle_sha256"]):
        raise ValueError("invalid bundle digest")
    if value["reproducible"] is not True or value["host_contract"] != "passed":
        raise ValueError("candidate did not pass all gates")
    if value["registry_status"] not in {"new", "already-registered"}:
        raise ValueError("invalid registry status")
    if value["planned_channel"] not in {"stable", "beta", "nightly"}:
        raise ValueError("invalid planned channel")
    if not isinstance(value["requires"], dict):
        raise ValueError("candidate requires must be an object")
    if "build_environment" in value:
        policy = json.loads(
            (Path(__file__).parents[1] / "config/builder-environment.json").read_text()
        )
        environment = value["build_environment"]
        if not isinstance(environment, dict) or any(
            environment.get(key) != expected for key, expected in policy.items()
        ):
            raise ValueError("candidate build environment violates builder policy")
        if environment.get("builder_commit") != value["builder_commit"]:
            raise ValueError("candidate builder commit mismatch")
        if not COMMIT_RE.fullmatch(str(environment.get("host_commit", ""))):
            raise ValueError("candidate host commit invalid")
    if not re.fullmatch(r"github-actions://run/[0-9]+/[a-z0-9.-]+", value["artifact_candidate"]):
        raise ValueError("candidate artifact is not a GitHub Actions run artifact")
    return value


def candidate_release(value: dict[str, Any]) -> dict[str, Any]:
    """Shared immutable release mapping for legacy preparation and trusted DB promotion."""
    return {
        "version": value["version"],
        "channel": value["planned_channel"],
        "artifact": {
            "url": canonical_public_artifact_url(value["module_id"], value["version"]),
            "sha256": value["bundle_sha256"],
        },
        "bundle_format_version": value["bundle_format_version"],
        "source_commit": value["source_commit"],
        "source_tag": value["source_tag"],
        "requires": value["requires"],
    }


def store_candidate(source: Path, root: Path) -> tuple[Path, bool]:
    value = validate_candidate(json.loads(source.read_text(encoding="utf-8")))
    destination = root / value["module_id"] / value["version"] / "provenance.json"
    rendered = canonical_json(value)
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        comparable_fields = REQUIRED - {"artifact_candidate", "builder_commit"}
        if any(existing.get(field) != value[field] for field in comparable_fields):
            raise ValueError("candidate version already exists with different provenance")
        return destination, False
    destination.parent.mkdir(parents=True)
    destination.write_text(rendered, encoding="utf-8")
    return destination, True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provenance", type=Path)
    parser.add_argument("--output", type=Path, default=Path("candidates"))
    args = parser.parse_args()
    try:
        destination, created = store_candidate(args.provenance, args.output)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"path": str(destination), "created": created}))


if __name__ == "__main__":
    main()
