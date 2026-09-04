from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.ocp_builder import (
    BuilderError,
    ModulePolicy,
    SourceIdentity,
    load_policies,
    orchestrate,
    parse_tag,
    run_frontend_scripts,
    validate_source,
)
from scripts.registry_candidate import store_candidate, validate_candidate


def identity(module_id: str = "statistics", version: str = "0.4.0") -> SourceIdentity:
    return SourceIdentity(
        ModulePolicy(
            module_id,
            f"oklabflensburg/ocp-module-{module_id}",
            "first-party",
            "oklabflensburg",
            "AGPL-3.0-only",
        ),
        f"v{version}",
        version,
        "a" * 40,
        1,
    )


def write_source(root: Path, source_identity: SourceIdentity) -> None:
    module_id, version = source_identity.policy.module_id, source_identity.version
    backend_name = f"ocp-module-{module_id}"
    (root / "backend").mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "module.yaml").write_text(
        yaml.safe_dump(
            {
                "id": module_id,
                "version": version,
                "backend": {"package": backend_name},
                "frontend": {"package": f"@open-city-planner/{module_id}"},
                "requires": {"host": ">=0.2.0,<1.0.0", "sdk": ">=1.0.0,<2.0.0", "modules": {}},
            }
        )
    )
    (root / "backend" / "pyproject.toml").write_text(
        f'[project]\nname = "{backend_name}"\nversion = "{version}"\n'
    )
    (root / "frontend" / "package.json").write_text(
        json.dumps({"name": f"@open-city-planner/{module_id}", "version": version})
    )
    (root / "frontend" / "module.json").write_text(
        json.dumps({"id": module_id, "version": version})
    )


@pytest.mark.parametrize("tag", ["0.4.0", "v01.2.3", "v1.2", "main", "v1.2.3/evil"])
def test_tag_parser_fails_closed(tag: str) -> None:
    with pytest.raises(BuilderError, match="SemVer"):
        parse_tag(tag)


def test_tag_parser_accepts_release_and_prerelease() -> None:
    assert parse_tag("v0.4.0") == "0.4.0"
    assert parse_tag("v1.2.3-rc.1+build.2") == "1.2.3-rc.1+build.2"


def test_allowlist_contains_only_expected_first_party_pilots() -> None:
    version, policies = load_policies()
    assert version == 1
    assert set(policies) == {"statistics", "analysis-areas"}
    assert all(policy.classification == "first-party" for policy in policies.values())


def test_non_first_party_repository_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "modules.yaml"
    config.write_text(
        "builder_version: 1\nmodules:\n  bad:\n    repository: outside/bad\n"
        "    classification: first-party\n    publisher: outside\n    license: MIT\n"
        "    host_contract:\n      services: []\n"
    )
    with pytest.raises(BuilderError, match="outside the first-party"):
        load_policies(config)


def test_source_contract_accepts_generic_module(tmp_path: Path) -> None:
    source_identity = identity()
    write_source(tmp_path, source_identity)
    validate_source(tmp_path, source_identity)


def test_frontend_build_is_executed_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.ocp_builder.run",
        lambda command, **kwargs: commands.append(command) or "",
    )
    run_frontend_scripts(
        tmp_path,
        {"scripts": {"build": "node build"}},
    )
    assert commands == [["corepack", "pnpm", "run", "build"]]


def test_frontend_contract_check_is_executed_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.ocp_builder.run",
        lambda command, **kwargs: commands.append(command) or "",
    )
    run_frontend_scripts(tmp_path, {"scripts": {"contract:check": "vitest"}})
    assert commands == [["corepack", "pnpm", "run", "contract:check"]]


def test_frontend_build_is_optional_when_script_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.ocp_builder.run",
        lambda command, **kwargs: commands.append(command) or "",
    )
    run_frontend_scripts(tmp_path, {"scripts": {"test": "vitest"}})
    assert commands == [["corepack", "pnpm", "run", "test"]]


def test_frontend_build_failure_aborts_before_candidate_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_identity = identity()
    monkeypatch.setattr("scripts.ocp_builder.validate_host_verifier_checkout", lambda root: None)
    monkeypatch.setattr(
        "scripts.ocp_builder.prepare_checkout",
        lambda policy, tag, destination: source_identity,
    )

    def fail_build(command, **kwargs):
        if command[-1] == "build":
            raise BuilderError("frontend build failed")
        return ""

    def fake_build_once(source, output, source_identity, host_root):
        run_frontend_scripts(source, {"scripts": {"build": "node build"}})
        raise AssertionError("failed frontend build unexpectedly returned")

    monkeypatch.setattr("scripts.ocp_builder.run", fail_build)
    monkeypatch.setattr("scripts.ocp_builder.build_once", fake_build_once)
    monkeypatch.setattr(
        "scripts.ocp_builder.create_candidate",
        lambda *args: pytest.fail("candidate generation must not run"),
    )
    with pytest.raises(BuilderError, match="frontend build failed"):
        orchestrate("statistics", "v0.4.0", tmp_path, tmp_path / "host", "1", "beta")


def test_backend_only_source_is_supported(tmp_path: Path) -> None:
    source_identity = identity()
    write_source(tmp_path, source_identity)
    manifest = yaml.safe_load((tmp_path / "module.yaml").read_text())
    del manifest["frontend"]
    (tmp_path / "module.yaml").write_text(yaml.safe_dump(manifest))
    validate_source(tmp_path, source_identity)


@pytest.mark.parametrize(
    "field,value,error", [("id", "other", "id"), ("version", "0.4.1", "version")]
)
def test_manifest_identity_mismatch_fails(
    tmp_path: Path, field: str, value: str, error: str
) -> None:
    source_identity = identity()
    write_source(tmp_path, source_identity)
    manifest = yaml.safe_load((tmp_path / "module.yaml").read_text())
    manifest[field] = value
    (tmp_path / "module.yaml").write_text(yaml.safe_dump(manifest))
    with pytest.raises(BuilderError, match=error):
        validate_source(tmp_path, source_identity)


def candidate() -> dict:
    return {
        "schema_version": 1,
        "module_id": "statistics",
        "version": "0.4.0",
        "classification": "first-party",
        "source_repository": "https://github.com/oklabflensburg/ocp-module-statistics",
        "source_tag": "v0.4.0",
        "source_commit": "a" * 40,
        "builder_version": 1,
        "builder_commit": "b" * 40,
        "bundle_format_version": 1,
        "bundle_sha256": "c" * 64,
        "artifact_candidate": "github-actions://run/123/statistics-0.4.0",
        "reproducible": True,
        "host_contract": "passed",
        "planned_channel": "beta",
        "requires": {"host": ">=0.2.0,<1.0.0", "sdk": ">=1.0.0,<2.0.0", "modules": {}},
        "registry_status": "new",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("module_id", "unknown"),
        ("source_tag", "v0.4.1"),
        ("source_commit", "main"),
        ("bundle_sha256", "bad"),
        ("reproducible", False),
        ("host_contract", "failed"),
        ("planned_channel", "latest"),
        ("artifact_candidate", "https://attacker.invalid/file.ocp"),
    ],
)
def test_invalid_candidate_fails_closed(field: str, value: object) -> None:
    value_candidate = candidate()
    value_candidate[field] = value
    with pytest.raises(ValueError):
        validate_candidate(value_candidate)


def test_candidate_storage_is_idempotent_and_immutable(tmp_path: Path) -> None:
    source = tmp_path / "provenance.json"
    source.write_text(json.dumps(candidate()))
    destination, created = store_candidate(source, tmp_path / "candidates")
    assert created
    assert store_candidate(source, tmp_path / "candidates") == (destination, False)
    changed = candidate()
    changed["bundle_sha256"] = "d" * 64
    source.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="different provenance"):
        store_candidate(source, tmp_path / "candidates")


def test_reproducibility_mismatch_fails_before_host_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_identity = identity()
    calls = 0

    monkeypatch.setattr("scripts.ocp_builder.validate_host_verifier_checkout", lambda root: None)
    monkeypatch.setattr(
        "scripts.ocp_builder.prepare_checkout",
        lambda policy, tag, destination: source_identity,
    )

    def fake_build(source, output, source_identity, host_root):
        nonlocal calls
        calls += 1
        output.mkdir(parents=True)
        artifact = output / "statistics-0.4.0.ocp"
        artifact.write_bytes(f"build-{calls}".encode())
        return artifact

    monkeypatch.setattr("scripts.ocp_builder.build_once", fake_build)
    monkeypatch.setattr(
        "scripts.ocp_builder.run_host_verifier",
        lambda *args: pytest.fail("host verifier must not run"),
    )
    with pytest.raises(BuilderError, match="non-reproducible"):
        orchestrate("statistics", "v0.4.0", tmp_path, tmp_path / "host", "1", "beta")


def test_unknown_module_fails_before_host_access(tmp_path: Path) -> None:
    with pytest.raises(BuilderError, match="non-allowlisted"):
        orchestrate("community", "v1.0.0", tmp_path, tmp_path / "host", "1", "beta")


def test_two_independent_git_clones_resolve_annotated_and_lightweight_tags(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=source, check=True)
    (source / "file").write_text("content")
    subprocess.run(["git", "add", "file"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=source, check=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=source, check=True)
    subprocess.run(["git", "tag", "-a", "v1.0.1", "-m", "release"], cwd=source, check=True)
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    for tag in ("v1.0.0", "v1.0.1"):
        clone = tmp_path / tag
        subprocess.run(["git", "clone", "-q", "--no-checkout", str(source), str(clone)], check=True)
        actual = subprocess.check_output(
            ["git", "rev-parse", f"{tag}^{{commit}}"], cwd=clone, text=True
        ).strip()
        assert actual == expected
