import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.promote_candidate import PromotionBlocked, main, promote, reviewed_candidate
from scripts.verify_artifacts import ArtifactVerificationError
from tests.test_ocp_builder import candidate


@pytest.fixture
def root(tmp_path):
    shutil.copytree(Path(__file__).parents[1] / "registry", tmp_path / "registry")
    return tmp_path


def test_promotion_updates_stable_and_preserves_history(root):
    value = candidate()
    value["planned_channel"] = "stable"
    before = json.loads((root / "registry/modules/statistics.json").read_text())
    urls = []

    def download(artifact, path):
        urls.append(artifact.artifact_url)
        return value["bundle_sha256"]

    assert promote(root, value, downloader=download)
    module = json.loads((root / "registry/modules/statistics.json").read_text())
    assert module["versions"][:-1] == before["versions"]
    index = json.loads((root / "dist/index.json").read_text())
    item = next(m for m in index["modules"] if m["id"] == "statistics")
    assert item["channels"]["stable"] == {
        "version": "0.4.0",
        "sha256": value["bundle_sha256"],
    }
    assert urls == [
        "https://packages.stadtplaner.oklabflensburg.de/modules/statistics/0.4.0/statistics-0.4.0.ocp"
    ]
    assert not promote(root, value, downloader=lambda *args: pytest.fail("no-op downloads"))
    conflict = copy.deepcopy(value)
    conflict["bundle_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="conflicts"):
        promote(root, conflict)


@pytest.mark.parametrize("field,value", [("reproducible", False), ("host_contract", "failed")])
def test_failed_gates_cannot_promote(root, field, value):
    data = candidate()
    data[field] = value
    with pytest.raises(ValueError):
        promote(root, data)
    assert not (root / "dist").exists()


def test_temporary_artifact_alone_cannot_promote(root):
    def missing(*args):
        raise ValueError("permanent artifact unavailable")

    before = (root / "registry/modules/statistics.json").read_bytes()
    with pytest.raises(ValueError, match="unavailable"):
        promote(root, candidate(), downloader=missing)
    assert before == (root / "registry/modules/statistics.json").read_bytes()
    assert not (root / "dist").exists()


def test_wrong_permanent_digest_fails_before_writes(root):
    with pytest.raises(ValueError, match="digest mismatch"):
        promote(root, candidate(), downloader=lambda *args: "f" * 64)
    assert not (root / "dist").exists()


def test_unreviewed_candidate_is_not_accepted(root, monkeypatch):
    import subprocess

    def git(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "missing")

    monkeypatch.setattr("scripts.promote_candidate.subprocess.run", git)
    with pytest.raises(ValueError, match="reviewed main"):
        reviewed_candidate(root, "statistics", "0.4.0")


def test_candidate_approval_requires_remote_main(root):
    remote = root / "remote"
    remote.mkdir()

    def git(*args, cwd=remote):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("commit", "--allow-empty", "-m", "reviewed baseline")
    git("init", cwd=root)
    git("remote", "add", "origin", str(remote), cwd=root)
    path = "candidates/statistics/0.4.0/provenance.json"
    (root / path).parent.mkdir(parents=True)
    (root / path).write_text(json.dumps(candidate()))
    with pytest.raises(ValueError, match="reviewed main"):
        reviewed_candidate(root, "statistics", "0.4.0")
    git("switch", "-c", "automation/statistics-v0.4.0")
    (remote / path).parent.mkdir(parents=True)
    (remote / path).write_text(json.dumps(candidate()))
    git("add", "candidates")
    git("commit", "-m", "candidate not yet approved")
    with pytest.raises(ValueError, match="reviewed main"):
        reviewed_candidate(root, "statistics", "0.4.0")
    git("switch", "main")
    git("merge", "--ff-only", "automation/statistics-v0.4.0")
    assert reviewed_candidate(root, "statistics", "0.4.0") == candidate()


def test_missing_hosting_creates_only_blocked_plan(root, monkeypatch):
    monkeypatch.chdir(root)
    monkeypatch.setattr("scripts.promote_candidate.reviewed_candidate", lambda *args: candidate())

    def blocked(*args):
        raise PromotionBlocked("Permanent artifact unavailable")

    monkeypatch.setattr("scripts.promote_candidate.promote", blocked)
    monkeypatch.setattr(
        "sys.argv",
        [
            "promote-candidate",
            "--module",
            "statistics",
            "--version",
            "0.4.0",
            "--prepare-blocked",
        ],
    )
    before = (root / "registry/modules/statistics.json").read_bytes()
    main()
    plan = json.loads((root / "promotion-plans/statistics/0.4.0.json").read_text())
    assert plan["status"] == "blocked"
    assert plan["bundle_sha256"] == candidate()["bundle_sha256"]
    assert before == (root / "registry/modules/statistics.json").read_bytes()
    assert not (root / "dist").exists()


def test_http_404_is_explicit_hosting_block(root):
    def download(*args):
        raise ArtifactVerificationError("artifact request failed with HTTP 404")

    with pytest.raises(PromotionBlocked):
        promote(root, candidate(), downloader=download)
