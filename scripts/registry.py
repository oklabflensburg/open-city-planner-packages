"""Registry v1 loading, validation, immutability, and deterministic rendering."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, unquote, urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

SCHEMA_VERSION = 1
BUNDLE_FORMAT_VERSION = 1
MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHANNELS = ("stable", "beta", "nightly")
CLASSIFICATIONS = ("first-party", "reviewed-community")
RELEASE_KEYS = {
    "version",
    "channel",
    "artifact",
    "bundle_format_version",
    "source_commit",
    "source_tag",
    "requires",
}
MODULE_KEYS = {
    "schema_version",
    "id",
    "name",
    "description",
    "publisher",
    "classification",
    "source_repository",
    "license",
    "homepage",
    "documentation_url",
    "versions",
}
PROTECTED_MODULE_FIELDS = {
    "classification": (
        "{module_id}: classification cannot change after publication "
        "({existing} → {proposed})"
    ),
    "source_repository": (
        '{module_id}: published source_repository is immutable; existing "{existing}", '
        'proposed "{proposed}"'
    ),
    "license": (
        "{module_id}: published license is immutable in registry schema v1; "
        'existing "{existing}", proposed "{proposed}"'
    ),
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RegistryValidationError(ValueError):
    """Raised when registry source violates the v1 contract."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RegistryValidationError(f'duplicate JSON key "{key}"')
        result[key] = value
    return result


def decode_json(text: str, origin: str) -> dict[str, Any]:
    try:
        value = json.loads(text, object_pairs_hook=_object_without_duplicate_keys)
    except (json.JSONDecodeError, RegistryValidationError) as exc:
        raise RegistryValidationError(f"{origin}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistryValidationError(f"{origin}: root must be a JSON object")
    return value


def load_registry(registry_root: Path) -> list[dict[str, Any]]:
    envelope_path = registry_root / "registry.json"
    if not envelope_path.is_file():
        raise RegistryValidationError(f"missing registry source envelope: {envelope_path}")
    envelope = decode_json(envelope_path.read_text(encoding="utf-8"), str(envelope_path))
    _exact_keys(envelope, {"schema_version"}, {"schema_version"}, str(envelope_path))
    _schema_version(envelope["schema_version"], str(envelope_path))

    modules_dir = registry_root / "modules"
    paths = sorted(modules_dir.glob("*.json")) if modules_dir.exists() else []
    modules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        module = decode_json(path.read_text(encoding="utf-8"), str(path))
        validate_module(module, str(path))
        module_id = module["id"]
        if module_id in seen:
            raise RegistryValidationError(f'{path}: duplicate module ID "{module_id}"')
        if path.stem != module_id:
            raise RegistryValidationError(
                f'{path}: file name must be "{module_id}.json", not "{path.name}"'
            )
        seen.add(module_id)
        modules.append(module)
    return sorted(modules, key=lambda module: module["id"])


def validate_module(module: dict[str, Any], origin: str, expected_id: str | None = None) -> None:
    required = {
        "schema_version",
        "id",
        "name",
        "publisher",
        "classification",
        "source_repository",
        "license",
        "versions",
    }
    _exact_keys(module, MODULE_KEYS, required, origin)
    _schema_version(module["schema_version"], origin)
    module_id = _canonical_id(module["id"], f"{origin}.id")
    if expected_id is not None and expected_id != module_id:
        raise RegistryValidationError(
            f'{origin}: file name must be "{module_id}.json", not "{expected_id}.json"'
        )
    _nonempty_string(module["name"], f"{origin}.name", 120)
    _optional_string(module, "description", origin, 1000)
    _optional_https_url(module, "homepage", origin)
    _optional_https_url(module, "documentation_url", origin)
    _validate_publisher(module["publisher"], f"{origin}.publisher")

    classification = module["classification"]
    if classification not in CLASSIFICATIONS:
        raise RegistryValidationError(
            f"{origin}.classification: must be one of {', '.join(CLASSIFICATIONS)}"
        )
    source = _https_url(module["source_repository"], f"{origin}.source_repository")
    if classification == "first-party" and not (
        source.hostname == "github.com"
        and unquote(source.path).startswith("/oklabflensburg/")
    ):
        raise RegistryValidationError(
            f"{origin}.source_repository: first-party source must be in github.com/oklabflensburg"
        )
    _nonempty_string(module["license"], f"{origin}.license", 255)

    versions = module["versions"]
    if not isinstance(versions, list) or not versions:
        raise RegistryValidationError(f"{origin}.versions: must be a non-empty array")
    seen_versions: set[str] = set()
    for position, release in enumerate(versions):
        release_origin = f"{origin}.versions[{position}]"
        _validate_release(release, release_origin, module_id, classification)
        version = release["version"]
        if version in seen_versions:
            raise RegistryValidationError(f'{release_origin}: duplicate version "{version}"')
        seen_versions.add(version)
    _validate_json_schema(module, REPOSITORY_ROOT / "schema" / "module-v1.schema.json", origin)


def _validate_publisher(value: Any, origin: str) -> None:
    if not isinstance(value, dict):
        raise RegistryValidationError(f"{origin}: must be an object")
    _exact_keys(value, {"id", "name"}, {"id", "name"}, origin)
    _canonical_id(value["id"], f"{origin}.id")
    _nonempty_string(value["name"], f"{origin}.name", 120)


def _validate_release(value: Any, origin: str, module_id: str, classification: str) -> None:
    if not isinstance(value, dict):
        raise RegistryValidationError(f"{origin}: must be an object")
    required = RELEASE_KEYS - {"source_tag"}
    _exact_keys(value, RELEASE_KEYS, required, origin)
    version = _semver(value["version"], f"{origin}.version")
    channel = value["channel"]
    if channel not in CHANNELS:
        raise RegistryValidationError(f"{origin}.channel: must be one of {', '.join(CHANNELS)}")
    if channel == "stable" and SEMVER_RE.fullmatch(version).group(4) is not None:
        raise RegistryValidationError(f"{origin}: stable releases cannot use prerelease versions")

    artifact = value["artifact"]
    if not isinstance(artifact, dict):
        raise RegistryValidationError(f"{origin}.artifact: must be an object")
    _exact_keys(artifact, {"url", "sha256"}, {"url", "sha256"}, f"{origin}.artifact")
    validate_artifact_url(
        artifact["url"], classification, module_id, version, f"{origin}.artifact.url"
    )
    if not isinstance(artifact["sha256"], str) or not SHA256_RE.fullmatch(artifact["sha256"]):
        raise RegistryValidationError(f"{origin}.artifact.sha256: must be 64 lowercase hex chars")
    if value["bundle_format_version"] != BUNDLE_FORMAT_VERSION:
        raise RegistryValidationError(
            f"{origin}.bundle_format_version: only version 1 is supported"
        )
    if not isinstance(value["source_commit"], str) or not COMMIT_RE.fullmatch(
        value["source_commit"]
    ):
        raise RegistryValidationError(
            f"{origin}.source_commit: must be 40 or 64 lowercase hex chars"
        )
    _optional_string(value, "source_tag", origin, 255)
    _validate_requires(value["requires"], f"{origin}.requires", module_id)


def _validate_requires(value: Any, origin: str, module_id: str) -> None:
    if not isinstance(value, dict):
        raise RegistryValidationError(f"{origin}: must be an object")
    _exact_keys(value, {"host", "sdk", "modules"}, {"host", "sdk", "modules"}, origin)
    _version_range(value["host"], f"{origin}.host")
    _version_range(value["sdk"], f"{origin}.sdk")
    modules = value["modules"]
    if not isinstance(modules, dict):
        raise RegistryValidationError(f"{origin}.modules: must be an object")
    for dependency, constraint in modules.items():
        _canonical_id(dependency, f"{origin}.modules key")
        if dependency == module_id:
            raise RegistryValidationError(f"{origin}.modules: a module cannot depend on itself")
        _version_range(constraint, f"{origin}.modules.{dependency}")


def validate_artifact_url(
    url: str,
    classification: str,
    module_id: str,
    version: str,
    origin: str = "artifact URL",
) -> SplitResult:
    """Validate the single Registry v1 initial-artifact URL policy."""

    parsed = _https_url(url, origin)
    path = unquote(parsed.path)
    if not path.endswith(".ocp"):
        raise RegistryValidationError(f"{origin}: artifact path must end in .ocp")
    hosted = (
        parsed.hostname == "packages.stadtplaner.oklabflensburg.de"
        and path.startswith(f"/modules/{module_id}/{version}/")
    )
    github_match = re.fullmatch(
        r"/([^/]+)/[^/]+/releases/download/([^/]+)/[^/]+\.ocp", path
    )
    github_release = parsed.hostname == "github.com" and github_match is not None
    if github_match is not None and github_match.group(2) not in {version, f"v{version}"}:
        raise RegistryValidationError(
            f"{origin}: GitHub release tag must bind the exact module version"
        )
    if not hosted and not github_release:
        raise RegistryValidationError(
            f"{origin}: stable hosting policy permits the registry module path or GitHub Releases"
        )
    if classification == "first-party" and github_release and not path.startswith(
        "/oklabflensburg/"
    ):
        raise RegistryValidationError(
            f"{origin}: first-party GitHub artifacts must be under oklabflensburg"
        )
    return parsed


def _https_url(value: Any, origin: str) -> SplitResult:
    if not isinstance(value, str) or not value:
        raise RegistryValidationError(f"{origin}: must be a non-empty HTTPS URL")
    parsed = urlsplit(value)
    try:
        invalid_port = parsed.port not in {None, 443}
    except ValueError:
        invalid_port = True
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or invalid_port
        or parsed.query
        or parsed.fragment
        or "\\" in value
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise RegistryValidationError(
            f"{origin}: must be HTTPS without credentials, query parameters, or fragments"
        )
    return parsed


def _optional_https_url(value: dict[str, Any], key: str, origin: str) -> None:
    if key in value:
        _https_url(value[key], f"{origin}.{key}")


def _canonical_id(value: Any, origin: str) -> str:
    if not isinstance(value, str) or len(value) > 63 or not MODULE_ID_RE.fullmatch(value):
        raise RegistryValidationError(f"{origin}: must be a lowercase kebab-case module ID")
    return value


def _semver(value: Any, origin: str) -> str:
    if not isinstance(value, str) or not SEMVER_RE.fullmatch(value):
        raise RegistryValidationError(f"{origin}: must be a complete SemVer version")
    return value


def _version_range(value: Any, origin: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RegistryValidationError(f"{origin}: must be a canonical SemVer range")
    for clause in value.split(","):
        match = re.match(r"^(>=|<=|==|!=|>|<)(.+)$", clause)
        if match is None:
            raise RegistryValidationError(f"{origin}: each clause requires an explicit operator")
        _semver(match.group(2), origin)


def _schema_version(value: Any, origin: str) -> None:
    if value != SCHEMA_VERSION or isinstance(value, bool):
        raise RegistryValidationError(f"{origin}: unsupported schema_version {value!r}")


def _nonempty_string(value: Any, origin: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise RegistryValidationError(f"{origin}: must be a non-empty trimmed string")


def _optional_string(value: dict[str, Any], key: str, origin: str, maximum: int) -> None:
    if key in value:
        _nonempty_string(value[key], f"{origin}.{key}", maximum)


def _exact_keys(value: dict[str, Any], allowed: set[str], required: set[str], origin: str) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        raise RegistryValidationError(f"{origin}: unknown fields: {', '.join(unknown)}")
    if missing:
        raise RegistryValidationError(f"{origin}: missing fields: {', '.join(missing)}")


def _validate_json_schema(value: Any, schema_path: Path, origin: str) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(value)
    except (OSError, json.JSONDecodeError, SchemaError, ValidationError) as exc:
        raise RegistryValidationError(f"{origin}: JSON Schema validation failed: {exc}") from exc


def semver_key(version: str) -> tuple[Any, ...]:
    match = SEMVER_RE.fullmatch(version)
    if match is None:
        raise RegistryValidationError(f"invalid SemVer: {version}")
    prerelease = match.group(4)
    if prerelease is None:
        prerelease_key: tuple[Any, ...] = (1,)
    else:
        identifiers = tuple(
            (0, int(part)) if part.isdigit() else (1, part) for part in prerelease.split(".")
        )
        prerelease_key = (0, identifiers)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease_key)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_index(modules: list[dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for module in sorted(modules, key=lambda item: item["id"]):
        channels: dict[str, dict[str, str]] = {}
        for channel in CHANNELS:
            releases = [item for item in module["versions"] if item["channel"] == channel]
            if releases:
                current = max(releases, key=lambda item: semver_key(item["version"]))
                channels[channel] = {
                    "version": current["version"],
                    "sha256": current["artifact"]["sha256"],
                }
        entries.append(
            {
                "id": module["id"],
                "name": module["name"],
                "publisher": module["publisher"],
                "classification": module["classification"],
                "channels": channels,
                "metadata": f'/modules/{module["id"]}.json',
            }
        )
    index = {"schema_version": SCHEMA_VERSION, "modules": entries}
    _validate_json_schema(index, REPOSITORY_ROOT / "schema" / "registry-v1.schema.json", "index")
    return index


def canonical_module(module: dict[str, Any]) -> dict[str, Any]:
    result = dict(module)
    result["versions"] = sorted(module["versions"], key=lambda item: semver_key(item["version"]))
    return result


def load_registry_from_git(reference: str, repository: Path) -> list[dict[str, Any]]:
    baseline_exists = subprocess.run(
        ["git", "cat-file", "-e", f"{reference}:registry/registry.json"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if baseline_exists.returncode != 0:
        return []

    def git_show(path: str) -> str:
        process = subprocess.run(
            ["git", "show", f"{reference}:{path}"],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            raise RegistryValidationError(
                f"cannot read immutable baseline {reference}:{path}: {process.stderr.strip()}"
            )
        return process.stdout

    envelope = decode_json(
        git_show("registry/registry.json"), f"{reference}:registry/registry.json"
    )
    _schema_version(envelope.get("schema_version"), f"{reference}:registry/registry.json")
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", reference, "registry/modules"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0:
        raise RegistryValidationError(f"cannot list immutable baseline {reference}")
    modules = []
    for path in sorted(line for line in listing.stdout.splitlines() if line.endswith(".json")):
        module = decode_json(git_show(path), f"{reference}:{path}")
        validate_module(module, f"{reference}:{path}", expected_id=Path(path).stem)
        modules.append(module)
    return modules


def validate_immutability(
    current_modules: list[dict[str, Any]], base_modules: list[dict[str, Any]]
) -> None:
    current_by_id = {module["id"]: module for module in current_modules}
    for base_module in base_modules:
        module_id = base_module["id"]
        current = current_by_id.get(module_id)
        if current is None:
            raise RegistryValidationError(
                f'{module_id}: published module metadata cannot be removed'
            )
        _validate_module_provenance_immutability(current, base_module)
        current_releases = {release["version"]: release for release in current["versions"]}
        for base_release in base_module["versions"]:
            version = base_release["version"]
            if version not in current_releases:
                raise RegistryValidationError(
                    f"{module_id}@{version}: published release cannot be removed"
                )
            if current_releases[version] != base_release:
                raise RegistryValidationError(
                    f"{module_id}@{version}: published release metadata is immutable; "
                    "publish a new version"
                )


def _validate_module_provenance_immutability(
    current: dict[str, Any], published: dict[str, Any]
) -> None:
    """Protect stable module identity while leaving presentation metadata editable."""

    module_id = published["id"]
    published_publisher_id = published["publisher"]["id"]
    proposed_publisher_id = current["publisher"]["id"]
    if proposed_publisher_id != published_publisher_id:
        raise RegistryValidationError(
            f'{module_id}: published publisher.id is immutable; existing '
            f'"{published_publisher_id}", proposed "{proposed_publisher_id}"'
        )

    for field, error_template in PROTECTED_MODULE_FIELDS.items():
        existing = published[field]
        proposed = current[field]
        if proposed == existing:
            continue
        raise RegistryValidationError(
            error_template.format(
                module_id=module_id,
                existing=existing,
                proposed=proposed,
            )
        )
