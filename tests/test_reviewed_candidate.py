"""Review binding and bounded artifact transport never trust working-tree candidate JSON."""

import copy
import json
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

from scripts.reviewed_candidate import (
    CandidateApprovalError,
    GitHubCandidateSource,
    candidate_digest,
    download_reviewed_artifact,
    extract_reviewed_archive,
)

FIXTURE = Path(__file__).parent / "fixtures/reviewed-statistics-0.4.0"
DIGEST = "70be3863818e41678fe7c7adeef69edbf865a18d7494a50021cf52e043239626"


def evidence():
    return json.loads((FIXTURE / "github-evidence.json").read_text())


def reviewed():
    return GitHubCandidateSource(evidence().__getitem__).load("statistics", "0.4.0", 41, DIGEST)


def test_real_review_binding_and_original_archive(tmp_path):
    approved = reviewed()
    assert approved.approval_identity == "p3t3r67x0"
    assert approved.merge_commit == "d54085286e5ed0d8df37715b6ed3fca465ee3dbb"
    assert candidate_digest(approved.value) == DIGEST
    assert approved.value["bundle_sha256"] == (
        "6bec701141f8c77dff4c4054ae095be31efe262f9cc3eab6414f68be57ae5423"
    )
    path = extract_reviewed_archive(FIXTURE / "candidate.zip", approved, tmp_path)
    assert path.stat().st_size == 28555
    approved.value["source_commit"] = "f" * 40
    assert candidate_digest(approved.value) == DIGEST  # returned copies cannot change approval


@pytest.mark.parametrize(
    "case",
    [
        "open",
        "bot",
        "wrong-base",
        "unrelated",
        "changed-main",
        "changed-head",
        "changed-merge",
        "digest",
    ],
)
def test_unreviewed_or_stale_candidate_rejected(case):
    responses = evidence()
    pr = responses["pulls/41"]
    digest = DIGEST
    if case == "open":
        pr["merged"] = False
    elif case == "bot":
        pr["merged_by"]["type"] = "Bot"
    elif case == "wrong-base":
        pr["base"]["ref"] = "unreviewed"
    elif case == "unrelated":
        responses["pulls/41/files?per_page=100"] = []
    elif case == "digest":
        digest = "f" * 64
    else:
        import base64

        ref = {
            "changed-main": "main",
            "changed-head": pr["head"]["sha"],
            "changed-merge": pr["merge_commit_sha"],
        }[case]
        content = responses[f"contents/candidates/statistics/0.4.0/provenance.json?ref={ref}"]
        value = json.loads(base64.b64decode(content["content"]))
        value["source_commit"] = "f" * 40
        content["content"] = base64.b64encode(json.dumps(value).encode()).decode()
    with pytest.raises(CandidateApprovalError):
        GitHubCandidateSource(responses.__getitem__).load("statistics", "0.4.0", 41, digest)


@pytest.mark.parametrize("case", ["traversal", "duplicate", "symlink", "provenance", "digest"])
def test_archive_rejects_unreviewed_or_unsafe_members(tmp_path, case):
    with ZipFile(FIXTURE / "candidate.zip") as archive:
        members = {entry.filename: archive.read(entry) for entry in archive.infolist()}
    if case == "traversal":
        members["../escape"] = b"unsafe"
    elif case == "provenance":
        value = json.loads(members["provenance.json"])
        value["planned_channel"] = "beta"
        members["provenance.json"] = json.dumps(value).encode()
    elif case == "digest":
        members["statistics-0.4.0.ocp"] = b"wrong"
    target = tmp_path / "bad.zip"
    with ZipFile(target, "w") as archive:
        for name, payload in members.items():
            info = ZipInfo(name)
            if case == "symlink" and name == "statistics-0.4.0.ocp":
                info.external_attr = 0o120777 << 16
            archive.writestr(info, payload)
        if case == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("provenance.json", members["provenance.json"])
    with pytest.raises(CandidateApprovalError):
        extract_reviewed_archive(target, reviewed(), tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("case", ["expired", "missing", "wrong-run", "wrong-builder"])
def test_retained_artifact_identity_gate(case, tmp_path):
    run = {
        "conclusion": "success",
        "head_sha": reviewed().value["builder_commit"],
        "repository": {"full_name": "oklabflensburg/open-city-planner-packages"},
        "path": ".github/workflows/ocp-builder.yml",
    }
    artifact = {
        "id": 1,
        "name": "statistics-v0.4.0",
        "expired": case == "expired",
        "size_in_bytes": 29242,
        "workflow_run": {"head_sha": run["head_sha"]},
    }
    if case == "wrong-run":
        run["path"] = ".github/workflows/untrusted.yml"
    if case == "wrong-builder":
        artifact["workflow_run"]["head_sha"] = "f" * 40

    def api(path):
        if "/artifacts?" in path:
            return {"artifacts": [] if case == "missing" else [artifact]}
        return copy.deepcopy(run)

    with pytest.raises(CandidateApprovalError):
        download_reviewed_artifact(reviewed(), tmp_path, api=api)
    assert not (tmp_path / "candidate.zip").exists()


def test_archive_binds_entire_candidate_including_compatibility(tmp_path):
    value = reviewed().value
    value["requires"]["sdk"] = ">=1.0.0"
    changed = replace(
        reviewed(), canonical=json.dumps(value), candidate_sha256=candidate_digest(value)
    )
    with pytest.raises(CandidateApprovalError, match="provenance"):
        extract_reviewed_archive(FIXTURE / "candidate.zip", changed, tmp_path)
