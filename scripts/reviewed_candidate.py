"""Trusted GitHub evidence adapter; no module source checkout or execution."""

import base64
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from scripts.registry import canonical_json, decode_json, validate_module_id, validate_semver
from scripts.registry_candidate import validate_candidate

REPOSITORY = "oklabflensburg/open-city-planner-packages"
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


class CandidateApprovalError(ValueError):
    """Missing, stale or mismatched reviewed evidence."""


def candidate_digest(candidate: dict) -> str:
    return hashlib.sha256(canonical_json(candidate).encode()).hexdigest()


def github_json(path: str):
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/{path}"], capture_output=True, check=False, timeout=60
    )
    if result.returncode:
        raise CandidateApprovalError("GitHub evidence unavailable")
    return json.loads(result.stdout)


@dataclass(frozen=True)
class ReviewedCandidate:
    canonical: str
    candidate_sha256: str
    approval_reference: str
    approval_identity: str
    merge_commit: str

    @property
    def value(self):
        # A new copy prevents caller mutation between verification and commit.
        return json.loads(self.canonical)


class GitHubCandidateSource:
    def __init__(self, api=github_json):
        self.api = api

    def load(self, module_id, version, approval_pr, expected_candidate_sha256):
        validate_module_id(module_id)
        validate_semver(version)
        if not isinstance(approval_pr, int) or approval_pr <= 0:
            raise CandidateApprovalError("A merged candidate PR is required")
        pr = self.api(f"pulls/{approval_pr}")
        if not (
            pr.get("merged")
            and pr["base"]["ref"] == "main"
            and pr["base"]["repo"]["full_name"] == REPOSITORY
            and pr.get("merged_by", {}).get("type") == "User"
        ):
            raise CandidateApprovalError("Candidate requires a human-merged PR into Registry main")
        commits = (pr["head"]["sha"], pr["merge_commit_sha"])
        if not all(re.fullmatch(r"[0-9a-f]{40}", commit or "") for commit in commits):
            raise CandidateApprovalError("Invalid review commit identity")
        path = f"candidates/{module_id}/{version}/provenance.json"
        # PR must actually review this file; merely citing an unrelated merged PR is invalid.
        files = self.api(f"pulls/{approval_pr}/files?per_page=100")
        if not any(f["filename"] == path and f["status"] in {"added", "modified"} for f in files):
            raise CandidateApprovalError("Approval PR does not contain this candidate")
        values = []
        for ref in (*commits, "main"):
            content = self.api(f"contents/{path}?ref={ref}")
            if content.get("encoding") != "base64":
                raise CandidateApprovalError("Candidate evidence has no file contents")
            raw = base64.b64decode(content["content"]).decode("utf-8")
            values.append(validate_candidate(decode_json(raw, "reviewed candidate")))
        value = values[0]
        if any(candidate_digest(v) != expected_candidate_sha256 for v in values):
            raise CandidateApprovalError("Candidate differs from approved digest or current main")
        if (value["module_id"], value["version"]) != (module_id, version):
            raise CandidateApprovalError("Candidate path/identity mismatch")
        if not re.fullmatch(r"[0-9a-f]{40}", value["builder_commit"]):
            raise CandidateApprovalError("Promotion requires a known builder commit")
        return ReviewedCandidate(
            canonical_json(value),
            expected_candidate_sha256,
            f"https://github.com/{REPOSITORY}/pull/{approval_pr}",
            pr["merged_by"]["login"],
            pr["merge_commit_sha"],
        )


def extract_reviewed_archive(archive: Path, reviewed: ReviewedCandidate, destination: Path) -> Path:
    """Exact, bounded members read individually; never extract paths from a ZIP."""
    value = reviewed.value
    filename = f"{value['module_id']}-{value['version']}.ocp"
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise CandidateApprovalError("Candidate archive exceeds limit")
    with ZipFile(archive) as bundle:
        entries = bundle.infolist()
        expected = {"provenance.json", filename, filename + ".sha256"}
        if len(entries) != 3 or {e.filename for e in entries} != expected:
            raise CandidateApprovalError("Unexpected candidate archive contents")
        if any(
            e.file_size > MAX_ARCHIVE_BYTES or (e.external_attr >> 16) & 0o170000 == 0o120000
            for e in entries
        ):
            raise CandidateApprovalError("Unsafe candidate archive member")
        evidence = decode_json(bundle.read("provenance.json").decode(), "archive provenance")
        if candidate_digest(evidence) != reviewed.candidate_sha256:
            raise CandidateApprovalError("Archive provenance differs from reviewed candidate")
        payload = bundle.read(filename)
        if hashlib.sha256(payload).hexdigest() != value["bundle_sha256"]:
            raise CandidateApprovalError("Candidate bundle digest mismatch")
        checksum = bundle.read(filename + ".sha256").decode().split()
        if checksum != [value["bundle_sha256"], filename]:
            raise CandidateApprovalError("Candidate checksum sidecar mismatch")
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = destination / filename
    with target.open("xb") as stream:
        stream.write(payload)
    return target


def download_reviewed_artifact(reviewed, destination, *, api=github_json):
    value = reviewed.value
    run_id = value["artifact_candidate"].split("/")[3]
    run = api(f"actions/runs/{run_id}")
    if not (
        run["conclusion"] == "success"
        and run["head_sha"] == value["builder_commit"]
        and run["repository"]["full_name"] == REPOSITORY
        and run["path"] == ".github/workflows/ocp-builder.yml"
    ):
        raise CandidateApprovalError("Candidate run identity does not match builder evidence")
    # v1 builder recorded module-version in provenance; upload-artifact used module-source_tag.
    locator_name = f"{value['module_id']}-{value['version']}"
    if value["artifact_candidate"] != f"github-actions://run/{run_id}/{locator_name}":
        raise CandidateApprovalError("Unexpected candidate artifact locator")
    listing = api(f"actions/runs/{run_id}/artifacts?per_page=100")
    matches = [
        a
        for a in listing["artifacts"]
        if a["name"] == f"{value['module_id']}-{value['source_tag']}"
    ]
    if len(matches) != 1 or matches[0]["expired"]:
        raise CandidateApprovalError("Reviewed artifact unavailable; no rebuild recovery")
    artifact = matches[0]
    if (
        artifact["size_in_bytes"] > MAX_ARCHIVE_BYTES
        or artifact["workflow_run"]["head_sha"] != value["builder_commit"]
    ):
        raise CandidateApprovalError("Artifact identity/size mismatch")
    archive = destination / "candidate.zip"
    with archive.open("xb") as stream:
        result = subprocess.run(
            ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{int(artifact['id'])}/zip"],
            stdout=stream,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
    if result.returncode:
        raise CandidateApprovalError("Reviewed artifact download failed")
    return extract_reviewed_archive(archive, reviewed, destination / "materialized")
