"""Request-local DTO projection over batched repository reads; no retained ORM state."""

from collections import defaultdict

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from scripts.registry import semver_key
from web.backend.app.api.models_registry_v2 import (
    ModuleDetail,
    ModulePage,
    ModuleSearch,
    ModuleSummary,
    PublishedVersion,
    PublisherPage,
    RegistryPublisher,
    RegistryPublisherDetail,
    VersionPage,
)
from web.backend.app.db.repository import RegistryDatabaseRepository


class NotFound(LookupError):
    pass


def search_rank(module, publisher, query):
    module_id, name, query = module.id.lower(), module.name.lower(), query.lower()
    if module_id == query:
        return 0
    if name == query:
        return 1
    if module_id.startswith(query) or name.startswith(query):
        return 2
    if query in module_id or query in name:
        return 3
    return 4


class RegistryReadService:
    def __init__(self, repository: RegistryDatabaseRepository):
        self.repository = repository

    def list_modules(
        self,
        *,
        limit=50,
        offset=0,
        module_id=None,
        publisher=None,
        classification=None,
        channel=None,
        host=None,
        sdk=None,
        q=None,
    ):
        candidates = self.repository.module_candidates(
            module_id=module_id, publisher=publisher, classification=classification, q=q
        )
        ids = [module.id for module, _ in candidates]
        versions = defaultdict(list)
        for row in self.repository.version_summaries(ids):
            versions[row.module_id].append(row)
        channels = self.repository.channel_targets(ids)
        host_version = Version(host) if host is not None else None
        sdk_version = Version(sdk) if sdk is not None else None

        def matches(module):
            targets = channels.get(module.id, {})
            if channel is not None and channel not in targets:
                return False
            for row in versions[module.id]:
                if channel is not None and row.version != targets[channel]["version"]:
                    continue
                if host_version is not None and host_version not in SpecifierSet(
                    row.host_compatibility
                ):
                    continue
                if sdk_version is not None and sdk_version not in SpecifierSet(
                    row.sdk_compatibility
                ):
                    continue
                return True
            return False

        candidates = [(module, pub) for module, pub in candidates if matches(module)]
        if q is not None:
            candidates.sort(key=lambda row: (search_rank(*row, q), row[0].id))
        items = []
        for module, pub in candidates[offset : offset + limit]:
            targets = channels.get(module.id, {})
            items.append(
                ModuleSummary(
                    id=module.id,
                    name=module.name,
                    description=module.description,
                    publisher={"id": pub.id, "name": pub.name},
                    classification=module.classification,
                    license=module.license,
                    source_repository=module.source_repository,
                    homepage=module.homepage,
                    documentation_url=module.documentation_url,
                    stable_version=targets.get("stable", {}).get("version"),
                    channels=targets,
                    version_count=len(versions[module.id]),
                )
            )
        values = dict(items=items, total=len(candidates), limit=limit, offset=offset)
        return ModulePage(**values) if q is None else ModuleSearch(**values, query=q)

    def get_module(self, module_id):
        page = self.list_modules(module_id=module_id)
        if not page.items:
            raise NotFound("Module not found")
        return ModuleDetail(
            **page.items[0].model_dump(), versions_url=f"/api/v1/modules/{module_id}/versions"
        )

    def get_channels(self, module_id):
        return self.get_module(module_id).channels

    def _versions(self, module_id, *, version=None, limit=50, offset=0):
        if not self.repository.module_candidates(module_id=module_id):
            raise NotFound("Module not found")
        rows = self.repository.published_versions(module_id, version)
        # Stable exact-string ASC tie-break for build metadata with equal SemVer precedence.
        rows.sort(key=lambda row: row[0].version)
        rows.sort(key=lambda row: semver_key(row[0].version), reverse=True)
        selected = rows[offset : offset + limit]
        dependencies = defaultdict(dict)
        for dependency in self.repository.version_dependencies(
            module_id, [row[0].version for row in selected]
        ):
            dependencies[dependency.owner_version][dependency.dependency_module_id] = (
                dependency.specifier
            )
        items = []
        for release, artifact, source_repository, evidence in selected:
            provenance = (
                {}
                if evidence is None
                else {
                    key: getattr(evidence, key)
                    for key in (
                        "builder_version",
                        "builder_commit",
                        "host_commit",
                        "reproducible",
                        "host_contract_status",
                    )
                }
                | {"environment": evidence.environment_json}
            )
            items.append(
                PublishedVersion(
                    module_id=module_id,
                    version=release.version,
                    historical_publication_channel=release.historical_publication_channel,
                    bundle_format_version=release.bundle_format_version,
                    artifact={
                        "url": release.artifact_original_url,
                        "sha256": artifact.digest,
                        "byte_size": artifact.byte_size,
                        "storage_locator": artifact.storage_locator,
                    },
                    source={
                        "repository": source_repository,
                        "tag": release.source_tag,
                        "commit": release.source_commit,
                    },
                    compatibility={
                        "host": release.host_compatibility,
                        "sdk": release.sdk_compatibility,
                    },
                    dependencies=dependencies[release.version],
                    published_at=release.published_at,
                    provenance=provenance,
                )
            )
        return VersionPage(items=items, total=len(rows), limit=limit, offset=offset)

    def list_versions(self, module_id, *, limit=50, offset=0):
        return self._versions(module_id, limit=limit, offset=offset)

    def get_version(self, module_id, version):
        page = self._versions(module_id, version=version, limit=1)
        if not page.items:
            raise NotFound("Version not found")
        return page.items[0]

    def list_publishers(self, *, limit=50, offset=0):
        rows = self.repository.published_publishers()
        return PublisherPage(
            items=[RegistryPublisher(**row._mapping) for row in rows[offset : offset + limit]],
            total=len(rows),
            limit=limit,
            offset=offset,
        )

    def get_publisher(self, publisher_id, *, limit=50, offset=0):
        rows = self.repository.published_publishers(publisher_id)
        if not rows:
            raise NotFound("Publisher not found")
        return RegistryPublisherDetail(
            **rows[0]._mapping,
            modules=self.list_modules(publisher=publisher_id, limit=limit, offset=offset),
        )
