"""Internal metadata repository. The caller owns the session and transaction."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from scripts.registry import validate_module
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

    def module_structure(self, module: Module, publisher=None) -> dict[str, Any]:
        if publisher is None:
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

    def release_structure(
        self, version: ModuleVersion, artifact=None, dependencies=None
    ) -> dict[str, Any]:
        if artifact is None:
            artifact = self.session.get(Artifact, version.artifact_id)
        if dependencies is None:
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
        self,
        module_id: str,
        release: dict[str, Any],
        *,
        historical_order: int | None = None,
        provenance_values: dict[str, Any] | None = None,
    ) -> bool:
        """Insert validated release metadata or reject conflicts; never promote channels.

        Returns True only for an insertion. Row locking serializes same-module calls
        through dependency insertion, so an identical concurrent retry sees a complete
        version. Historical imports retain unknown evidence; trusted promotion supplies
        explicit provenance after review and durable artifact verification.
        """
        module = self.session.scalar(select(Module).where(Module.id == module_id).with_for_update())
        if module is None:
            raise RegistryConflict(f"Missing module: {module_id}")
        validate_module({**self.module_structure(module), "versions": [release]}, "DB version")
        promoted = provenance_values is not None
        evidence = provenance_values if promoted else self.historical_provenance(module, release)
        previous = self.session.get(ModuleVersion, (module_id, release["version"]))
        if previous is not None:
            if historical_order is not None and previous.historical_order != historical_order:
                raise RegistryConflict("Historical version order conflict")
            if (
                self.release_structure(previous) != release
                or (previous.published_at is not None) != promoted
            ):
                raise RegistryConflict(
                    f"Immutable version conflict: {module_id}@{release['version']}"
                )
            provenance = self.session.get(BuildProvenance, previous.build_provenance_id)
            if provenance is None or any(
                getattr(provenance, field) != value for field, value in evidence.items()
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
        provenance = BuildProvenance(**evidence, imported_at=None if promoted else func.now())
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
                published_at=func.now() if promoted else None,
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

    def project_v1(self, module_id: str | None = None) -> list[dict[str, Any]]:
        """Shared import/HTTP projection in three batched queries; preserve stored order.

        Only modules with published versions participate. Candidate provenance and
        unattached artifacts never become releases through this projection.
        """
        modules = self.module_candidates(module_id=module_id)
        ids = [module.id for module, _publisher in modules]
        releases: dict[str, list[dict[str, Any]]] = {key: [] for key in ids}
        dependencies: dict[tuple[str, str], list[ModuleDependency]] = {}
        for dependency in self.session.scalars(
            select(ModuleDependency).where(ModuleDependency.owner_module_id.in_(ids))
        ):
            dependencies.setdefault(
                (dependency.owner_module_id, dependency.owner_version), []
            ).append(dependency)
        for version, artifact in self.session.execute(
            select(ModuleVersion, Artifact)
            .join(Artifact, ModuleVersion.artifact_id == Artifact.id)
            .where(ModuleVersion.module_id.in_(ids))
            .order_by(ModuleVersion.module_id, ModuleVersion.historical_order)
        ):
            releases[version.module_id].append(
                self.release_structure(
                    version, artifact, dependencies.get((version.module_id, version.version), [])
                )
            )
        return [
            {**self.module_structure(module, publisher), "versions": releases[module.id]}
            for module, publisher in sorted(modules, key=lambda row: row[0].id)
        ]

    def channel_targets(
        self, module_ids: list[str] | None = None
    ) -> dict[str, dict[str, dict[str, str]]]:
        result: dict[str, dict[str, dict[str, str]]] = {}
        rows = self.session.execute(
            select(ModuleChannel, Artifact.digest)
            .join(
                ModuleVersion,
                (ModuleChannel.module_id == ModuleVersion.module_id)
                & (ModuleChannel.version == ModuleVersion.version),
            )
            .join(Artifact, ModuleVersion.artifact_id == Artifact.id)
            .where(ModuleChannel.module_id.in_(module_ids) if module_ids is not None else True)
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

    def module_candidates(self, *, module_id=None, publisher=None, classification=None, q=None):
        """Published-only candidates; no joins to unattached candidate evidence."""
        query = (
            select(Module, Publisher)
            .join(Publisher)
            .where(
                select(ModuleVersion.module_id).where(ModuleVersion.module_id == Module.id).exists()
            )
        )
        for column, value in (
            (Module.id, module_id),
            (Module.publisher_id, publisher),
            (Module.classification, classification),
        ):
            if value is not None:
                query = query.where(column == value)
        if q is not None:
            # Treat user wildcard characters literally; values remain bound parameters.
            pattern = "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            query = query.where(
                or_(
                    *(
                        column.ilike(pattern, escape="!")
                        for column in (
                            Module.id,
                            Module.name,
                            Module.description,
                            Publisher.name,
                        )
                    )
                )
            )
        return self.session.execute(query.order_by(Module.name, Module.id)).all()

    def version_summaries(self, module_ids):
        return self.session.execute(
            select(
                ModuleVersion.module_id,
                ModuleVersion.version,
                ModuleVersion.host_compatibility,
                ModuleVersion.sdk_compatibility,
            ).where(ModuleVersion.module_id.in_(module_ids))
        ).all()

    def published_versions(self, module_id, version=None):
        query = (
            select(ModuleVersion, Artifact, Module.source_repository, BuildProvenance)
            .join(Artifact, ModuleVersion.artifact_id == Artifact.id)
            .join(Module, ModuleVersion.module_id == Module.id)
            .outerjoin(BuildProvenance, ModuleVersion.build_provenance_id == BuildProvenance.id)
            .where(ModuleVersion.module_id == module_id)
        )
        if version is not None:
            query = query.where(ModuleVersion.version == version)
        return self.session.execute(query).all()

    def version_dependencies(self, module_id, versions):
        return self.session.scalars(
            select(ModuleDependency)
            .where(
                ModuleDependency.owner_module_id == module_id,
                ModuleDependency.owner_version.in_(versions),
            )
            .order_by(ModuleDependency.dependency_module_id)
        ).all()

    def published_publishers(self, publisher_id=None):
        query = (
            select(Publisher.id, Publisher.name, func.count(Module.id).label("module_count"))
            .join(Module, Module.publisher_id == Publisher.id)
            .where(
                select(ModuleVersion.module_id).where(ModuleVersion.module_id == Module.id).exists()
            )
            .group_by(Publisher.id, Publisher.name)
            .order_by(Publisher.name, Publisher.id)
        )
        if publisher_id is not None:
            query = query.where(Publisher.id == publisher_id)
        return self.session.execute(query).all()

    def schema_revision(self):
        revisions = self.session.scalars(text("SELECT version_num FROM alembic_version")).all()
        return revisions[0] if len(revisions) == 1 else None
