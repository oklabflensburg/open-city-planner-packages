"""Legacy/pre-writer-cutover JSON PR preparation; use registry_promote for Registry v2."""

import argparse
import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path

from scripts.build_registry import build
from scripts.registry import (
    MODULE_ID_RE,
    SEMVER_RE,
    canonical_json,
    load_registry,
    validate_immutability,
    validate_module,
)
from scripts.registry_candidate import candidate_release, validate_candidate
from scripts.verify_artifacts import ArtifactVerificationError, ReleaseCandidate, download_artifact


class PromotionBlocked(ValueError):
    """Approved candidate still lacks a permanent artifact."""


def reviewed_candidate(root: Path, module_id: str, version: str) -> dict:
    if not MODULE_ID_RE.fullmatch(module_id) or not SEMVER_RE.fullmatch(version):
        raise ValueError("invalid module/version")
    path = f"candidates/{module_id}/{version}/provenance.json"
    # Fetch main explicitly: an open candidate branch or a working-tree file is not approval.
    subprocess.run(["git", "fetch", "origin", "main"], cwd=root, check=True)
    result = subprocess.run(
        ["git", "show", f"origin/main:{path}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError("candidate is missing from reviewed main")
    value = validate_candidate(json.loads(result.stdout))
    if (value["module_id"], value["version"]) != (module_id, version):
        raise ValueError("candidate path/identity mismatch")
    return value


def promote(root: Path, candidate: dict, *, downloader=download_artifact) -> bool:
    if os.environ.get("PACKAGES_REGISTRY_WRITER_CUTOVER_ENABLED") == "true":
        raise PromotionBlocked("Legacy JSON publication is disabled after DB writer cutover")
    value = validate_candidate(candidate)
    module_id, version = value["module_id"], value["version"]
    modules = load_registry(root / "registry")
    updated = copy.deepcopy(modules)
    module = next((m for m in updated if m["id"] == module_id), None)
    if module is None or module["source_repository"] != value["source_repository"]:
        raise ValueError("candidate has no matching reviewed Registry identity")
    release = candidate_release(value)
    url = release["artifact"]["url"]
    previous = next((r for r in module["versions"] if r["version"] == version), None)
    if previous is not None:
        if previous != release:
            raise ValueError("existing Registry version conflicts with candidate")
        return False
    module["versions"].append(release)
    validate_module(module, "promotion")
    validate_immutability(updated, modules)
    # Actions artifacts are never Registry URLs. No writes occur until the permanent
    # canonical URL serves the exact reviewed bytes. Missing hosting blocks promotion.
    artifact = ReleaseCandidate(
        module_id=module_id,
        version=version,
        channel=value["planned_channel"],
        artifact_url=url,
        expected_sha256=value["bundle_sha256"],
        classification="first-party",
    )
    with tempfile.TemporaryDirectory(prefix="ocp-promotion-") as temporary:
        try:
            digest = downloader(artifact, Path(temporary) / f"{module_id}-{version}.ocp")
        except ArtifactVerificationError as exc:
            if "HTTP 404" in str(exc):
                raise PromotionBlocked(f"Permanent artifact unavailable: {url}") from exc
            raise
        if digest != value["bundle_sha256"]:
            raise ValueError("permanent artifact digest mismatch; promotion blocked")
    (root / "registry/modules" / f"{module_id}.json").write_text(canonical_json(module))
    build(root / "registry", root / "dist")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--prepare-blocked",
        action="store_true",
        help="Write a review plan, never Registry data, if hosting is missing",
    )
    args = parser.parse_args()
    root = Path.cwd()
    value = reviewed_candidate(root, args.module, args.version)
    try:
        changed = promote(root, value)
    except PromotionBlocked as exc:
        if not args.prepare_blocked:
            raise
        plan = root / "promotion-plans" / args.module / f"{args.version}.json"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(
            canonical_json(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "candidate": f"candidates/{args.module}/{args.version}/provenance.json",
                    "bundle_sha256": value["bundle_sha256"],
                    "planned_channel": value["planned_channel"],
                    "next_step": "Publish approved bytes immutably, then rerun promotion.",
                }
            )
        )
        print(str(exc))
        return
    print("Registry promotion prepared" if changed else "Already promoted; no changes")


if __name__ == "__main__":
    main()
