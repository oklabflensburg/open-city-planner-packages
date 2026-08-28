from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.build_registry import build
from scripts.registry import (
    RegistryValidationError,
    build_index,
    canonical_json,
    load_registry,
    load_registry_from_git,
    validate_immutability,
    validate_module,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "valid-registry"


@pytest.fixture
def module() -> dict:
    return json.loads(
        (FIXTURE_ROOT / "modules" / "energy-analysis.json").read_text(encoding="utf-8")
    )


def write_registry(root: Path, modules: list[tuple[str, dict]]) -> Path:
    registry = root / "registry"
    (registry / "modules").mkdir(parents=True)
    (registry / "registry.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    for filename, value in modules:
        (registry / "modules" / filename).write_text(json.dumps(value), encoding="utf-8")
    return registry


def invalid(module: dict, expected: str) -> None:
    with pytest.raises(RegistryValidationError, match=expected):
        validate_module(module, "fixture")


def test_valid_empty_registry(tmp_path: Path) -> None:
    assert load_registry(write_registry(tmp_path, [])) == []


def test_valid_module_metadata(module: dict) -> None:
    validate_module(module, "fixture")


def test_invalid_id(module: dict) -> None:
    module["id"] = "Energy_Analysis"
    invalid(module, "lowercase kebab-case")


@pytest.mark.parametrize("version", ["1.2", "01.2.3", "v1.2.3", "1.2.3-"])
def test_invalid_semver(module: dict, version: str) -> None:
    module["versions"][0]["version"] = version
    invalid(module, "complete SemVer")


def test_duplicate_module_id(tmp_path: Path, module: dict) -> None:
    registry = write_registry(
        tmp_path,
        [("energy-analysis.json", module), ("second-file.json", copy.deepcopy(module))],
    )
    with pytest.raises(RegistryValidationError, match="duplicate module ID"):
        load_registry(registry)


def test_duplicate_release_version(module: dict) -> None:
    module["versions"].append(copy.deepcopy(module["versions"][0]))
    invalid(module, "duplicate version")


@pytest.mark.parametrize("digest", ["abc", "g" * 64, "A" * 64])
def test_invalid_sha(module: dict, digest: str) -> None:
    module["versions"][0]["artifact"]["sha256"] = digest
    invalid(module, "64 lowercase hex")


def test_invalid_channel(module: dict) -> None:
    module["versions"][0]["channel"] = "latest"
    invalid(module, "must be one of stable, beta, nightly")


def test_http_artifact_url_rejected(module: dict) -> None:
    module["versions"][0]["artifact"]["url"] = "http://example.org/module.ocp"
    invalid(module, "must be HTTPS")


def test_url_credentials_rejected(module: dict) -> None:
    module["versions"][0]["artifact"]["url"] = (
        "https://user:secret@github.com/org/repo/releases/download/v1/module.ocp"
    )
    invalid(module, "without credentials")


def test_url_query_token_rejected(module: dict) -> None:
    module["versions"][0]["artifact"]["url"] += "?token=secret"
    invalid(module, "query parameters")


def test_non_default_https_port_rejected(module: dict) -> None:
    module["versions"][0]["artifact"]["url"] = (
        "https://github.com:444/oklabflensburg/energy-analysis/releases/download/"
        "v1.4.0/energy-analysis-1.4.0.ocp"
    )
    invalid(module, "must be HTTPS")


def test_mutable_github_release_alias_rejected(module: dict) -> None:
    module["versions"][0]["artifact"]["url"] = (
        "https://github.com/oklabflensburg/energy-analysis/releases/download/"
        "latest/energy-analysis-1.4.0.ocp"
    )
    invalid(module, "tag must bind the exact module version")


def test_unapproved_artifact_host_rejected(module: dict) -> None:
    module["classification"] = "reviewed-community"
    module["source_repository"] = "https://codeberg.org/community/energy-analysis"
    module["versions"][0]["artifact"]["url"] = "https://downloads.example.org/module.ocp"
    invalid(module, "hosting policy")


def test_missing_license(module: dict) -> None:
    del module["license"]
    invalid(module, "missing fields: license")


def test_unknown_schema_version(module: dict) -> None:
    module["schema_version"] = 2
    invalid(module, "unsupported schema_version")


def test_unknown_fields(module: dict) -> None:
    module["trust_me"] = True
    invalid(module, "unknown fields: trust_me")


def test_source_commit_must_match_host_contract(module: dict) -> None:
    module["versions"][0]["source_commit"] = "0" * 39
    invalid(module, "40 or 64 lowercase hex")


def test_bundle_format_version_is_v1(module: dict) -> None:
    module["versions"][0]["bundle_format_version"] = 2
    invalid(module, "only version 1")


def test_stable_release_cannot_be_prerelease(module: dict) -> None:
    module["versions"][0]["version"] = "1.4.0-rc.1"
    invalid(module, "stable releases cannot use prerelease")


def test_self_dependency_rejected(module: dict) -> None:
    module["versions"][0]["requires"]["modules"] = {"energy-analysis": ">=1.0.0"}
    invalid(module, "cannot depend on itself")


def test_index_selects_highest_release_per_channel(module: dict) -> None:
    older = copy.deepcopy(module["versions"][0])
    older["version"] = "1.3.9"
    older["artifact"]["sha256"] = "a" * 64
    module["versions"].insert(0, older)
    index = build_index([module])
    assert index["modules"][0]["channels"]["stable"] == {
        "version": "1.4.0",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    }


def test_deterministic_index_output(tmp_path: Path, module: dict) -> None:
    registry = write_registry(tmp_path, [("energy-analysis.json", module)])
    first = tmp_path / "first"
    second = tmp_path / "second"
    build(registry, first)
    build(registry, second)
    assert (first / "index.json").read_bytes() == (second / "index.json").read_bytes()
    assert (first / "modules" / "energy-analysis.json").read_bytes() == (
        second / "modules" / "energy-analysis.json"
    ).read_bytes()
    assert (first / "index.json").read_bytes().endswith(b"\n")
    assert canonical_json(build_index([module])).encode() == (first / "index.json").read_bytes()


def test_rebuild_removes_stale_generated_files(tmp_path: Path, module: dict) -> None:
    registry = write_registry(tmp_path, [("energy-analysis.json", module)])
    output = tmp_path / "output"
    build(registry, output)
    (output / "modules" / "stale.json").write_text("{}", encoding="utf-8")
    build(registry, output)
    assert not (output / "modules" / "stale.json").exists()


def test_build_refuses_registry_source_as_output(tmp_path: Path) -> None:
    registry = write_registry(tmp_path, [])
    with pytest.raises(RegistryValidationError, match="unsafe output"):
        build(registry, registry / "generated")


def test_immutable_release_cannot_change_digest(module: dict) -> None:
    current = copy.deepcopy(module)
    current["versions"][0]["artifact"]["sha256"] = "a" * 64
    with pytest.raises(RegistryValidationError, match="published release metadata is immutable"):
        validate_immutability([current], [module])


def test_immutable_release_can_add_version(module: dict) -> None:
    current = copy.deepcopy(module)
    new_release = copy.deepcopy(module["versions"][0])
    new_release["version"] = "1.4.1"
    new_release["artifact"]["sha256"] = "a" * 64
    current["versions"].append(new_release)
    validate_immutability([current], [module])


def test_initial_repository_without_registry_is_empty_baseline() -> None:
    repository = Path(__file__).parents[1]
    assert load_registry_from_git("main", repository) == []


def test_published_release_cannot_be_removed(module: dict) -> None:
    current = copy.deepcopy(module)
    current["versions"] = []
    with pytest.raises(RegistryValidationError, match="published release cannot be removed"):
        validate_immutability([current], [module])


def test_json_schemas_are_valid_json() -> None:
    schema_root = Path(__file__).parents[1] / "schema"
    for path in schema_root.glob("*.schema.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["$schema"].endswith("2020-12/schema")
