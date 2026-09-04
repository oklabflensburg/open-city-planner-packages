"""Central, fail-closed builder of record for first-party OCP modules."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import yaml
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from scripts.registry import RegistryValidationError, canonical_json, load_registry
from scripts.verify_artifacts import (
    ReleaseCandidate,
    download_artifact,
    run_host_verifier,
    validate_host_verifier_checkout,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "first-party-modules.yaml"
HOST_CONFIG_PATH = ROOT / ".github" / "ocp-host-verifier.json"
TAG_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class BuilderError(RuntimeError):
    """A source, build, integrity, or host-contract gate failed."""


@dataclass(frozen=True)
class ServiceContract:
    service_id: str
    version: int
    contract: str


@dataclass(frozen=True)
class ModulePolicy:
    module_id: str
    repository: str
    classification: str
    publisher: str
    license: str
    services: tuple[ServiceContract, ...] = ()

    @property
    def source_url(self) -> str:
        return f"https://github.com/{self.repository}"


@dataclass(frozen=True)
class SourceIdentity:
    policy: ModulePolicy
    tag: str
    version: str
    commit: str
    epoch: int


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=None if env is None else {**os.environ, **env},
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no details"
        raise BuilderError(f"command failed ({' '.join(command)}): {detail}")
    return result.stdout.strip()


def load_policies(path: Path = CONFIG_PATH) -> tuple[int, dict[str, ModulePolicy]]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BuilderError(f"invalid first-party configuration: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"builder_version", "modules"}:
        raise BuilderError("first-party configuration has unknown or missing fields")
    if value["builder_version"] != 1 or not isinstance(value["modules"], dict):
        raise BuilderError("only ocp-builder version 1 is supported")
    policies: dict[str, ModulePolicy] = {}
    required = {"repository", "classification", "publisher", "license", "host_contract"}
    for module_id, item in value["modules"].items():
        if not isinstance(item, dict) or set(item) != required:
            raise BuilderError(f"invalid policy for {module_id}")
        repository = item["repository"]
        if item["classification"] != "first-party" or not isinstance(repository, str):
            raise BuilderError(f"{module_id}: only first-party repositories are supported")
        if not re.fullmatch(r"oklabflensburg/[a-z0-9-]+", repository):
            raise BuilderError(f"{module_id}: repository is outside the first-party boundary")
        contract = item.pop("host_contract")
        if not isinstance(contract, dict) or set(contract) != {"services"}:
            raise BuilderError(f"invalid host contract for {module_id}")
        services: list[ServiceContract] = []
        for service in contract["services"]:
            if not isinstance(service, dict) or set(service) != {"id", "version", "contract"}:
                raise BuilderError(f"invalid service contract for {module_id}")
            if (
                not isinstance(service["version"], int)
                or service["version"] < 1
                or not re.fullmatch(r"[a-z0-9.-]+", service["id"])
                or not re.fullmatch(r"[A-Za-z0-9_.]+:[A-Za-z0-9_]+", service["contract"])
            ):
                raise BuilderError(f"invalid service contract for {module_id}")
            services.append(
                ServiceContract(service["id"], service["version"], service["contract"])
            )
        policies[module_id] = ModulePolicy(module_id=module_id, services=tuple(services), **item)
    return value["builder_version"], policies


def parse_tag(tag: str) -> str:
    match = TAG_RE.fullmatch(tag)
    if match is None:
        raise BuilderError("source tag must be an exact v-prefixed SemVer")
    return tag[1:]


def prepare_checkout(policy: ModulePolicy, tag: str, destination: Path) -> SourceIdentity:
    version = parse_tag(tag)
    destination.mkdir(parents=True)
    run(["git", "init", "--quiet"], cwd=destination)
    run(["git", "remote", "add", "origin", f"{policy.source_url}.git"], cwd=destination)
    run(
        [
            "git",
            "-c",
            "protocol.file.allow=never",
            "fetch",
            "--quiet",
            "--depth=1",
            "origin",
            f"refs/tags/{tag}",
        ],
        cwd=destination,
    )
    commit = run(["git", "rev-parse", "FETCH_HEAD^{commit}"], cwd=destination)
    if COMMIT_RE.fullmatch(commit) is None:
        raise BuilderError("source tag did not resolve to a full commit")
    run(["git", "checkout", "--quiet", "--detach", commit], cwd=destination)
    actual = run(["git", "rev-parse", "HEAD"], cwd=destination)
    if actual != commit:
        raise BuilderError("checkout does not match the commit resolved from the tag")
    epoch_text = run(["git", "show", "-s", "--format=%ct", commit], cwd=destination)
    identity = SourceIdentity(policy, tag, version, commit, int(epoch_text))
    validate_source(destination, identity)
    return identity


def _mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BuilderError(f"invalid {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuilderError(f"{path.name} must contain a mapping")
    return value


def validate_source(source: Path, identity: SourceIdentity) -> None:
    manifest = _mapping(source / "module.yaml")
    if manifest.get("id") != identity.policy.module_id:
        raise BuilderError("module.yaml.id does not match requested module")
    if str(manifest.get("version")) != identity.version:
        raise BuilderError("module.yaml.version does not match source tag")
    if not isinstance(manifest.get("backend"), dict):
        raise BuilderError("module.yaml must declare a backend")
    backend_file = source / "backend" / "pyproject.toml"
    try:
        backend = tomllib.loads(backend_file.read_text(encoding="utf-8"))["project"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise BuilderError(f"invalid backend pyproject.toml: {exc}") from exc
    if Version(str(backend.get("version"))) != Version(identity.version):
        raise BuilderError("backend project version does not match module manifest")
    declared_backend = manifest["backend"].get("package")
    if canonicalize_name(str(backend.get("name"))) != canonicalize_name(str(declared_backend)):
        raise BuilderError("backend project name does not match module manifest")
    frontend = manifest.get("frontend")
    if frontend is not None:
        try:
            package = json.loads((source / "frontend" / "package.json").read_text())
            module = json.loads((source / "frontend" / "module.json").read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise BuilderError(f"invalid frontend metadata: {exc}") from exc
        expected = (identity.policy.module_id, identity.version)
        if (module.get("id"), str(module.get("version"))) != expected:
            raise BuilderError("frontend module identity does not match module manifest")
        if package.get("name") != frontend.get("package"):
            raise BuilderError("frontend package name does not match module manifest")
        if str(package.get("version")) != identity.version:
            raise BuilderError("frontend package version does not match module manifest")


def _wheel_identity(path: Path) -> tuple[str, str]:
    with ZipFile(path) as archive:
        metadata_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise BuilderError("backend wheel must contain exactly one METADATA file")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
    fields = dict(line.split(": ", 1) for line in metadata.splitlines() if ": " in line)
    return fields.get("Name", ""), fields.get("Version", "")


def build_backend(source: Path, output: Path, identity: SourceIdentity) -> Path:
    wheel_dir = output / "backend"
    wheel_dir.mkdir(parents=True)
    run(
        ["uv", "build", "--wheel", "--clear", "--out-dir", str(wheel_dir)],
        cwd=source / "backend",
        env={"SOURCE_DATE_EPOCH": str(identity.epoch)},
    )
    wheels = list(wheel_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise BuilderError("backend build must produce exactly one wheel")
    manifest = _mapping(source / "module.yaml")
    name, version = _wheel_identity(wheels[0])
    if canonicalize_name(name) != canonicalize_name(manifest["backend"]["package"]):
        raise BuilderError("built wheel package does not match module manifest")
    if Version(version) != Version(identity.version):
        raise BuilderError("built wheel version does not match module manifest")
    return wheels[0]


def _copy_dereferenced(source: Path, destination: Path) -> None:
    if source.is_symlink():
        source = source.resolve(strict=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=False, ignore=shutil.ignore_patterns(".bin"))
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _archive_tree(root: Path, output: Path) -> None:
    paths = sorted(
        (path for path in root.rglob("*") if not path.is_symlink()), key=lambda p: p.as_posix()
    )
    with (
        output.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as archive,
    ):
        for path in paths:
            relative = path.relative_to(root).as_posix()
            info = archive.gettarinfo(str(path), arcname=relative)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 315532800
            info.mode = 0o755 if path.is_dir() or info.mode & 0o111 else 0o644
            with path.open("rb") if path.is_file() else _null_context() as payload:
                archive.addfile(info, payload if path.is_file() else None)


class _null_context:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


def build_frontend(source: Path, output: Path, identity: SourceIdentity) -> Path | None:
    manifest = _mapping(source / "module.yaml")
    if "frontend" not in manifest:
        return None
    frontend = source / "frontend"
    run(["corepack", "pnpm", "install", "--frozen-lockfile"], cwd=frontend, env={"CI": "true"})
    package = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    for script in ("typecheck", "test"):
        if script in package.get("scripts", {}):
            run(["corepack", "pnpm", script], cwd=frontend, env={"CI": "true"})
    artifact = output / "frontend" / f"{identity.policy.module_id}-{identity.version}.tgz"
    artifact.parent.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="ocp-frontend-") as temporary:
        deployed = Path(temporary) / "deployed"
        run(
            [
                "corepack",
                "pnpm",
                "--filter",
                package["name"],
                "deploy",
                "--prod",
                "--legacy",
                "--frozen-lockfile",
                str(deployed),
            ],
            cwd=frontend,
            env={"CI": "true"},
        )
        staging = Path(temporary) / "staging"
        staging.mkdir()
        entries = {"package.json", "module.json", *package.get("files", [])}
        for entry in sorted(entries):
            candidate = deployed / entry
            if candidate.exists():
                _copy_dereferenced(candidate, staging / entry)
        virtual = deployed / "node_modules" / ".pnpm"
        if virtual.is_dir():
            flat = staging / "node_modules"
            for modules in sorted(virtual.glob("*/node_modules")):
                for dependency in sorted(modules.iterdir()):
                    if dependency.name.startswith("@") and dependency.is_dir():
                        for scoped in sorted(dependency.iterdir()):
                            target = flat / dependency.name / scoped.name
                            if not target.exists():
                                _copy_dereferenced(scoped, target)
                    else:
                        target = flat / dependency.name
                        if dependency.is_dir() and not target.exists():
                            _copy_dereferenced(dependency, target)
        if any(path.is_symlink() for path in staging.rglob("*")):
            raise BuilderError("frontend staging tree contains symbolic links")
        _archive_tree(staging, artifact)
    return artifact


def assemble_bundle(
    source: Path,
    output: Path,
    identity: SourceIdentity,
    backend: Path,
    frontend: Path | None,
    host_root: Path,
) -> Path:
    host_python = host_root / "backend" / ".venv" / "bin" / "python"
    if not host_python.is_file():
        raise BuilderError("pinned host verifier environment is not installed")
    bundle = output / f"{identity.policy.module_id}-{identity.version}.ocp"
    command = [
        str(host_python),
        "-m",
        "app.cli.modules",
        "bundle",
        "build",
        "--manifest",
        str(source / "module.yaml"),
        "--backend",
        str(backend),
    ]
    if frontend is not None:
        command += ["--frontend", str(frontend)]
    command += [
        "--publisher",
        identity.policy.publisher,
        "--source-reference",
        f"releases/{identity.policy.module_id}/{identity.version}",
        "--source-repository",
        identity.policy.source_url,
        "--source-commit",
        identity.commit,
        "--source-tag",
        identity.tag,
        "--build-workflow",
        "package-hub/ocp-builder-v1",
        "--license",
        identity.policy.license,
        "--output",
        str(bundle),
    ]
    run(command, cwd=host_root / "backend", env={"SOURCE_DATE_EPOCH": str(identity.epoch)})
    if not bundle.is_file():
        raise BuilderError("host bundler did not produce the requested .ocp")
    return bundle


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def builder_commit() -> str:
    try:
        value = run(["git", "rev-parse", "HEAD"], cwd=ROOT)
    except BuilderError:
        return "unknown"
    return value if COMMIT_RE.fullmatch(value) else "unknown"


def build_once(source: Path, output: Path, identity: SourceIdentity, host_root: Path) -> Path:
    backend = build_backend(source, output, identity)
    frontend = build_frontend(source, output, identity)
    return assemble_bundle(source, output, identity, backend, frontend, host_root)


def _cli_json(
    host_root: Path, state_root: Path, environment: dict[str, str], *arguments: str
) -> dict[str, Any]:
    python = host_root / "backend" / ".venv" / "bin" / "python"
    output = run(
        [str(python), "-m", "app.cli.modules", "--root", str(state_root), *arguments],
        cwd=host_root / "backend",
        env=environment,
    )
    for line in reversed(output.splitlines()):
        if line.startswith("{"):
            value = json.loads(line)
            if isinstance(value, dict):
                return value
    raise BuilderError("host lifecycle command returned no JSON object")


def _dependency_candidates(manifest: dict[str, Any]) -> list[ReleaseCandidate]:
    registry = {item["id"]: item for item in load_registry(ROOT / "registry")}
    candidates: list[ReleaseCandidate] = []
    for module_id, constraint in manifest["requires"].get("modules", {}).items():
        module = registry.get(module_id)
        if module is None:
            raise BuilderError(f"host-contract dependency {module_id} is not registered")
        specifier = SpecifierSet(constraint)
        compatible = [
            release for release in module["versions"] if Version(release["version"]) in specifier
        ]
        if not compatible:
            raise BuilderError(f"no registered {module_id} release satisfies {constraint}")
        release = max(compatible, key=lambda item: Version(item["version"]))
        candidates.append(
            ReleaseCandidate(
                module_id=module_id,
                version=release["version"],
                channel=release["channel"],
                artifact_url=release["artifact"]["url"],
                expected_sha256=release["artifact"]["sha256"],
                classification=module["classification"],
            )
        )
    return candidates


def _bundle_has_migrations(path: Path) -> bool:
    try:
        with ZipFile(path) as archive:
            manifest = yaml.safe_load(archive.read("module.yaml"))
    except (KeyError, OSError, yaml.YAMLError) as exc:
        raise BuilderError(f"cannot inspect dependency bundle manifest: {exc}") from exc
    persistence = manifest.get("persistence", {}) if isinstance(manifest, dict) else {}
    return persistence.get("migrations") is True


def _enable_module(
    host_root: Path,
    state_root: Path,
    environment: dict[str, str],
    module_id: str,
    *,
    has_migrations: bool,
) -> None:
    if has_migrations:
        _cli_json(host_root, state_root, environment, "enable", module_id)
        return
    # A migration-free module must not be blocked by an unrelated incomplete Host graph.
    probe = """
from pathlib import Path
from app.cli.modules import _installer
installer = _installer(Path(__import__('sys').argv[1]))
installer.migration_preflight = None
print(installer.enable(__import__('sys').argv[2]).model_dump_json())
"""
    python = host_root / "backend" / ".venv" / "bin" / "python"
    run(
        [str(python), "-c", probe, str(state_root), module_id],
        cwd=host_root / "backend",
        env=environment,
    )


def _verify_public_services(
    host_root: Path,
    environment: dict[str, str],
    policy: ModulePolicy,
) -> None:
    if not policy.services:
        return
    contracts = json.dumps(
        [
            {"id": item.service_id, "version": item.version, "contract": item.contract}
            for item in policy.services
        ]
    )
    probe = """
import importlib
import json
import sys
from app.main import module_runtime

services = module_runtime.registry.get(sys.argv[1]).context.services
assert services is not None
for item in json.loads(sys.argv[2]):
    module_name, attribute = item["contract"].split(":", 1)
    contract = getattr(importlib.import_module(module_name), attribute)
    implementation = services.require(
        contract, service_id=item["id"], version=item["version"]
    )
    assert implementation is not None
"""
    python = host_root / "backend" / ".venv" / "bin" / "python"
    run(
        [str(python), "-c", probe, policy.module_id, contracts],
        cwd=host_root / "backend",
        env=environment,
    )


def run_host_lifecycle(
    artifact: Path, source: Path, identity: SourceIdentity, host_root: Path
) -> None:
    """Exercise the generic install/enable/discovery/disable lifecycle fail-closed."""

    manifest = _mapping(source / "module.yaml")
    with tempfile.TemporaryDirectory(prefix="ocp-host-state-") as state:
        state_root = Path(state)
        environment = {
            "ENABLED_MODULES": "",
            "OCP_BACKEND_MODULES": "",
            "OCP_ENABLED_INSTALLED_BACKEND_PATHS": "",
            "OCP_EXCLUDED_BUILTIN_MODULES": "",
            "OCP_FRONTEND_MODULES": "",
            "OCP_INSTALLED_FRONTEND_MODULE_ROOTS": "",
            "OCP_MODULE_INSTALL_ROOT": str(state_root),
        }
        for dependency in _dependency_candidates(manifest):
            dependency_path = state_root / f"{dependency.module_id}-{dependency.version}.ocp"
            actual = download_artifact(dependency, dependency_path)
            if actual != dependency.expected_sha256:
                raise BuilderError(
                    f"host-contract dependency {dependency.identity} digest mismatch"
                )
            _cli_json(host_root, state_root, environment, "verify", str(dependency_path))
            installed = _cli_json(
                host_root, state_root, environment, "install", str(dependency_path)
            )
            if installed.get("enabled") is not False:
                raise BuilderError("host installed a dependency as enabled")
            _enable_module(
                host_root,
                state_root,
                environment,
                dependency.module_id,
                has_migrations=_bundle_has_migrations(dependency_path),
            )

        verified = _cli_json(host_root, state_root, environment, "verify", str(artifact))
        if (verified.get("module_id"), verified.get("version")) != (
            identity.policy.module_id,
            identity.version,
        ):
            raise BuilderError("host verifier returned the wrong bundle identity")
        installed = _cli_json(host_root, state_root, environment, "install", str(artifact))
        if installed.get("enabled") is not False:
            raise BuilderError("host must install a candidate as disabled")
        inventory = _cli_json(host_root, state_root, environment, "list", "--format", "json")
        matching = [
            item
            for item in inventory.get("modules", [])
            if item.get("id") == identity.policy.module_id
        ]
        if len(matching) != 1 or matching[0].get("enabled") is not False:
            raise BuilderError("disabled candidate is missing from host inventory")
        has_migrations = manifest.get("persistence", {}).get("migrations") is True
        _enable_module(
            host_root,
            state_root,
            environment,
            identity.policy.module_id,
            has_migrations=has_migrations,
        )
        enabled = _cli_json(host_root, state_root, environment, "env", "--format", "json")
        if identity.policy.module_id not in enabled.get("ENABLED_MODULES", "").split(","):
            raise BuilderError("enabled candidate is missing from host discovery environment")
        if manifest.get("backend") and identity.policy.module_id not in enabled.get(
            "OCP_BACKEND_MODULES", ""
        ).split(","):
            raise BuilderError("enabled backend is missing from host discovery")
        if manifest.get("frontend") and identity.policy.module_id not in enabled.get(
            "OCP_FRONTEND_MODULES", ""
        ).split(","):
            raise BuilderError("enabled frontend is missing from host discovery")
        _verify_public_services(host_root, {**environment, **enabled}, identity.policy)
        _cli_json(host_root, state_root, environment, "disable", identity.policy.module_id)
        disabled = _cli_json(host_root, state_root, environment, "env", "--format", "json")
        if identity.policy.module_id in disabled.get("ENABLED_MODULES", "").split(","):
            raise BuilderError("disabled candidate remains enabled")
        _enable_module(
            host_root,
            state_root,
            environment,
            identity.policy.module_id,
            has_migrations=has_migrations,
        )


def create_candidate(
    output: Path,
    identity: SourceIdentity,
    digest: str,
    builder_version: int,
    run_id: str,
    planned_channel: str,
) -> dict[str, Any]:
    manifest = _mapping(output / "source" / "module.yaml")
    return {
        "schema_version": 1,
        "module_id": identity.policy.module_id,
        "version": identity.version,
        "classification": identity.policy.classification,
        "source_repository": identity.policy.source_url,
        "source_tag": identity.tag,
        "source_commit": identity.commit,
        "builder_version": builder_version,
        "builder_commit": builder_commit(),
        "bundle_format_version": 1,
        "bundle_sha256": digest,
        "artifact_candidate": f"github-actions://run/{run_id}/{identity.policy.module_id}-{identity.version}",
        "reproducible": True,
        "host_contract": "passed",
        "planned_channel": planned_channel,
        "requires": manifest["requires"],
    }


def check_registry_immutability(identity: SourceIdentity, digest: str) -> str:
    modules = {item["id"]: item for item in load_registry(ROOT / "registry")}
    module = modules.get(identity.policy.module_id)
    if module is None:
        raise BuilderError("allowlisted module has no reviewed Registry identity")
    for release in module["versions"]:
        if release["version"] == identity.version:
            if (
                release["source_commit"] != identity.commit
                or release["artifact"]["sha256"] != digest
            ):
                raise BuilderError("existing Registry version has different immutable provenance")
            return "already-registered"
    return "new"


def orchestrate(
    module_id: str,
    tag: str,
    output: Path,
    host_root: Path,
    run_id: str,
    planned_channel: str,
) -> dict[str, Any]:
    builder_version, policies = load_policies()
    if module_id not in policies:
        raise BuilderError(f'unknown or non-allowlisted module "{module_id}"')
    validate_host_verifier_checkout(host_root)
    output.mkdir(parents=True, exist_ok=True)
    first_source = output / "source"
    identity = prepare_checkout(policies[module_id], tag, first_source)
    second_source = output / "source-second"
    second_identity = prepare_checkout(policies[module_id], tag, second_source)
    if identity != second_identity:
        raise BuilderError("independent source resolutions disagree")
    first = build_once(first_source, output / "build-a", identity, host_root)
    second = build_once(second_source, output / "build-b", identity, host_root)
    first_digest, second_digest = sha256(first), sha256(second)
    if first_digest != second_digest:
        raise BuilderError(f"non-reproducible builds: {first_digest} != {second_digest}")
    candidate_dir = output / "candidate"
    candidate_dir.mkdir()
    artifact = candidate_dir / first.name
    shutil.copy2(first, artifact)
    (candidate_dir / f"{first.name}.sha256").write_text(f"{first_digest}  {first.name}\n")
    with tempfile.TemporaryDirectory(prefix="ocp-host-verify-") as state:
        release = ReleaseCandidate(
            module_id=module_id,
            version=identity.version,
            channel="beta",
            artifact_url="https://packages.stadtplaner.oklabflensburg.de/placeholder.ocp",
            expected_sha256=first_digest,
            classification="first-party",
        )
        run_host_verifier(release, artifact, host_root, Path(state))
    run_host_lifecycle(artifact, first_source, identity, host_root)
    if planned_channel not in {"stable", "beta", "nightly"}:
        raise BuilderError("planned channel must be stable, beta, or nightly")
    candidate = create_candidate(
        output, identity, first_digest, builder_version, run_id, planned_channel
    )
    candidate["registry_status"] = check_registry_immutability(identity, first_digest)
    (candidate_dir / "provenance.json").write_text(canonical_json(candidate), encoding="utf-8")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--host-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/ocp-builder"))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "0"))
    parser.add_argument("--channel", choices=("stable", "beta", "nightly"), default="beta")
    args = parser.parse_args()
    try:
        candidate = orchestrate(
            args.module,
            args.tag,
            args.output.resolve(),
            args.host_root.resolve(),
            args.run_id,
            args.channel,
        )
    except (BuilderError, RegistryValidationError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(candidate, sort_keys=True))


if __name__ == "__main__":
    main()
