"""Internal metadata repository. The caller owns the session and transaction."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from scripts.registry import canonical_module, validate_module
from web.backend.app.db.models import (
    Artifact,
    Base,
    BuildProvenance,
    Module,
    ModuleChannel,
    ModuleDependency,
    ModuleVersion,
    Publisher,
)


class RegistryConflict(ValueError):
    """Existing metadata differs from the requested immutable/imported state."""


class RegistryDatabaseRepository:
    def __init__(self, session: Session):
        self.session = session

    def ensure_record(self, model: type[Base], key: Mapping[str, Any], **values: Any) -> Base:
        """Insert or compare, never update. PostgreSQL arbitrates concurrent inserts."""
        expected = {**key, **values}
        query = select(model).filter_by(**key).execution_options(populate_existing=True)
        record = self.session.scalar(query)
        if record is None:
            self.session.execute(insert(model).values(**expected).on_conflict_do_nothing())
            record = self.session.scalar(query)
        if record is None or any(
            getattr(record, name) != value for name, value in expected.items()
        ):
            raise RegistryConflict(f"Conflicting {model.__tablename__} record: {dict(key)}")
        return record

    def module_structure(self, module: Module) -> dict[str, Any]:
        publisher = self.session.get(Publisher, module.publisher_id)
        result = {
            "schema_version": 1,
            "id": module.id,
            "name": module.name,
            "publisher": {"id": publisher.id, "name": publisher.name},
            "classification": module.classification,
            "license": module.license,
            "source_repository": module.source_repository,
        }
        for name in ("description", "homepage", "documentation_url"):
            if (value := getattr(module, name)) is not None:
                result[name] = value
        return result

    def release_structure(self, version: ModuleVersion) -> dict[str, Any]:
        artifact = self.session.get(Artifact, version.artifact_id)
        dependencies = self.session.scalars(
            select(ModuleDependency).filter_by(
                owner_module_id=version.module_id, owner_version=version.version
            )
        ).all()
        result = {
            "version": version.version,
            "channel": version.historical_publication_channel,
            "artifact": {"url": version.artifact_original_url, "sha256": artifact.digest},
            "bundle_format_version": version.bundle_format_version,
            "source_commit": version.source_commit,
            "requires": {
                "host": version.host_compatibility,
                "sdk": version.sdk_compatibility,
                "modules": {d.dependency_module_id: d.specifier for d in dependencies},
            },
        }
        if version.source_tag is not None:
            result["source_tag"] = version.source_tag
        return result

    def insert_published_version(
        self, module_id: str, release: dict[str, Any], *, historical_order: int | None = None
    ) -> bool:
        """Insert validated historical v1 metadata or reject conflicts; never promote channels.

        Returns True only for an insertion. Row locking serializes same-module calls
        through dependency insertion, so an identical concurrent retry sees a complete
        version. Evidence not present in v1 is explicitly unknown.
        """
        module = self.session.scalar(select(Module).where(Module.id == module_id).with_for_update())
        if module is None:
            raise RegistryConflict(f"Missing module: {module_id}")
        validate_module({**self.module_structure(module), "versions": [release]}, "DB version")
        previous = self.session.get(ModuleVersion, (module_id, release["version"]))
        if previous is not None:
            if historical_order is not None and previous.historical_order != historical_order:
                raise RegistryConflict("Historical version order conflict")
            if self.release_structure(previous) != release or previous.published_at is not None:
                raise RegistryConflict(
                    f"Immutable version conflict: {module_id}@{release['version']}"
                )
            provenance = self.session.get(BuildProvenance, previous.build_provenance_id)
            if provenance is None or any(
                getattr(provenance, field) != value
                for field, value in self.historical_provenance(module, release).items()
            ):
                raise RegistryConflict(f"Historical provenance conflict: {module_id}")
            artifact = self.session.get(Artifact, previous.artifact_id)
            if artifact.digest_algorithm != "sha256":
                raise RegistryConflict("Artifact digest algorithm conflict")
            return False

        if historical_order is None:
            maximum = self.session.scalar(
                select(func.max(ModuleVersion.historical_order)).where(
                    ModuleVersion.module_id == module_id
                )
            )
            historical_order = 0 if maximum is None else maximum + 1
        dependencies = release["requires"]["modules"]
        for target in dependencies:
            if self.session.get(Module, target) is None:
                raise RegistryConflict(f"Missing dependency module: {target}")
        artifact = self.ensure_record(
            Artifact, {"digest_algorithm": "sha256", "digest": release["artifact"]["sha256"]}
        )
        provenance = BuildProvenance(
            **self.historical_provenance(module, release), imported_at=func.now()
        )
        self.session.add(provenance)
        self.session.flush()
        self.session.add(
            ModuleVersion(
                module_id=module_id,
                historical_order=historical_order,
                version=release["version"],
                artifact_id=artifact.id,
                artifact_original_url=release["artifact"]["url"],
                build_provenance_id=provenance.id,
                bundle_format_version=release["bundle_format_version"],
                source_tag=release.get("source_tag"),
                source_commit=release["source_commit"],
                host_compatibility=release["requires"]["host"],
                sdk_compatibility=release["requires"]["sdk"],
                historical_publication_channel=release["channel"],
                published_at=None,
            )
        )
        self.session.flush()
        self.session.add_all(
            ModuleDependency(
                owner_module_id=module_id,
                owner_version=release["version"],
                dependency_module_id=target,
                specifier=specifier,
            )
            for target, specifier in sorted(dependencies.items())
        )
        self.session.flush()
        return True

    @staticmethod
    def historical_provenance(module: Module, release: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_repository": module.source_repository,
            "source_tag": release.get("source_tag"),
            "source_commit": release["source_commit"],
            "builder_version": None,
            "builder_commit": None,
            "host_commit": None,
            "reproducible": None,
            "host_contract_status": None,
            "environment_json": None,
        }

    def project_v1(self) -> list[dict[str, Any]]:
        """Internal parity projection, not a public compatibility API."""
        result = []
        for module in self.session.scalars(select(Module).order_by(Module.id)):
            versions = self.session.scalars(
                select(ModuleVersion)
                .filter_by(module_id=module.id)
                .order_by(ModuleVersion.historical_order)
            )
            result.append(
                canonical_module(
                    {
                        **self.module_structure(module),
                        "versions": [self.release_structure(version) for version in versions],
                    }
                )
            )
        return result

    def channel_targets(self) -> dict[str, dict[str, dict[str, str]]]:
        result: dict[str, dict[str, dict[str, str]]] = {}
        rows = self.session.execute(
            select(ModuleChannel, Artifact.digest)
            .join(
                ModuleVersion,
                (ModuleChannel.module_id == ModuleVersion.module_id)
                & (ModuleChannel.version == ModuleVersion.version),
            )
            .join(Artifact, ModuleVersion.artifact_id == Artifact.id)
            .order_by(ModuleChannel.module_id, ModuleChannel.channel)
        )
        for channel, digest in rows:
            result.setdefault(channel.module_id, {})[channel.channel] = {
                "version": channel.version,
                "sha256": digest,
            }
        return result

    def counts(self) -> dict[str, int]:
        return {
            model.__tablename__: self.session.scalar(select(func.count()).select_from(model))
            for model in (
                Publisher,
                Module,
                Artifact,
                BuildProvenance,
                ModuleVersion,
                ModuleDependency,
                ModuleChannel,
            )
        }
