"""Validated, read-only Registry v1 repository and deterministic search index."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from scripts.registry import load_registry, semver_key
from web.backend.app.models import (
    Compatibility,
    PackageDetail,
    PackageRelease,
    PackageSummary,
    Publisher,
    PublisherDetail,
    PublisherSummary,
)


@dataclass(frozen=True)
class PackageQuery:
    q: str = ""
    publisher: str | None = None
    classification: str | None = None
    channel: str | None = None
    host: str | None = None
    sdk: str | None = None
    sort: str = "relevance"


class RegistryRepository:
    """Load a validated Registry snapshot once and expose read-only projections."""

    def __init__(self, registry_root: Path) -> None:
        self.registry_root = registry_root
        self._modules = load_registry(registry_root)
        self._by_id = {module["id"]: module for module in self._modules}

    @property
    def package_count(self) -> int:
        return len(self._modules)

    def list_packages(self, query: PackageQuery) -> list[PackageSummary]:
        ranked = []
        for module in self._modules:
            if not self._matches_filters(module, query):
                continue
            rank = self._search_rank(module, query.q)
            if rank is None:
                continue
            ranked.append((rank, module))
        if query.sort == "name":
            ranked.sort(key=lambda item: (item[1]["name"].casefold(), item[1]["id"]))
        elif query.sort == "id":
            ranked.sort(key=lambda item: item[1]["id"])
        elif query.sort == "version":
            ranked.sort(
                key=lambda item: semver_key(self._latest_release(item[1])["version"]),
                reverse=True,
            )
        else:
            ranked.sort(key=lambda item: (item[0], item[1]["id"]))
        return [self._summary(module) for _, module in ranked]

    def package(self, module_id: str) -> PackageDetail | None:
        module = self._by_id.get(module_id)
        return self._detail(module) if module is not None else None

    def versions(self, module_id: str) -> list[PackageRelease] | None:
        module = self._by_id.get(module_id)
        if module is None:
            return None
        return [self._release(item) for item in self._sorted_releases(module)]

    def version(self, module_id: str, version: str) -> PackageRelease | None:
        module = self._by_id.get(module_id)
        if module is None:
            return None
        release = next((item for item in module["versions"] if item["version"] == version), None)
        return self._release(release) if release is not None else None

    def publishers(self) -> list[PublisherSummary]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for module in self._modules:
            grouped.setdefault(module["publisher"]["id"], []).append(module)
        return [self._publisher_summary(grouped[key]) for key in sorted(grouped)]

    def publisher(self, publisher_id: str) -> PublisherDetail | None:
        modules = [
            module for module in self._modules if module["publisher"]["id"] == publisher_id
        ]
        if not modules:
            return None
        summary = self._publisher_summary(modules)
        return PublisherDetail(**summary.model_dump(), packages=[self._summary(m) for m in modules])

    @staticmethod
    def _sorted_releases(module: dict[str, Any]) -> list[dict[str, Any]]:
        return sorted(
            module["versions"],
            key=lambda item: semver_key(item["version"]),
            reverse=True,
        )

    def _latest_release(self, module: dict[str, Any]) -> dict[str, Any]:
        return self._sorted_releases(module)[0]

    @staticmethod
    def _release(release: dict[str, Any]) -> PackageRelease:
        return PackageRelease.model_validate(release)

    def _summary(self, module: dict[str, Any]) -> PackageSummary:
        latest = self._latest_release(module)
        return PackageSummary(
            id=module["id"],
            name=module["name"],
            description=module.get("description"),
            publisher=Publisher.model_validate(module["publisher"]),
            classification=module["classification"],
            latest_version=latest["version"],
            latest_channel=latest["channel"],
            compatibility=Compatibility.model_validate(latest["requires"]),
            channels=sorted({item["channel"] for item in module["versions"]}),
        )

    def _detail(self, module: dict[str, Any]) -> PackageDetail:
        summary = self._summary(module)
        return PackageDetail(
            **summary.model_dump(),
            source_repository=module["source_repository"],
            license=module["license"],
            homepage=module.get("homepage"),
            documentation_url=module.get("documentation_url"),
            versions=[self._release(item) for item in self._sorted_releases(module)],
        )

    @staticmethod
    def _compatible(requirement: str, requested: str | None) -> bool:
        if requested is None:
            return True
        try:
            return Version(requested) in SpecifierSet(requirement)
        except (InvalidSpecifier, InvalidVersion):
            return False

    def _matches_filters(self, module: dict[str, Any], query: PackageQuery) -> bool:
        if query.publisher and module["publisher"]["id"] != query.publisher:
            return False
        if query.classification and module["classification"] != query.classification:
            return False
        releases = module["versions"]
        if query.channel and not any(item["channel"] == query.channel for item in releases):
            return False
        return any(
            self._compatible(item["requires"]["host"], query.host)
            and self._compatible(item["requires"]["sdk"], query.sdk)
            for item in releases
        )

    @staticmethod
    def _search_rank(module: dict[str, Any], raw_query: str) -> tuple[int, str] | None:
        query = raw_query.strip().casefold()
        if not query:
            return (0, module["id"])
        module_id = module["id"].casefold()
        name = module["name"].casefold()
        if query == module_id:
            bucket = 0
        elif query == name:
            bucket = 1
        elif module_id.startswith(query):
            bucket = 2
        elif name.startswith(query):
            bucket = 3
        elif query in module_id or query in name:
            bucket = 4
        elif query in (module.get("description") or "").casefold():
            bucket = 5
        elif query in module["publisher"]["id"].casefold() or query in module["publisher"][
            "name"
        ].casefold():
            bucket = 6
        elif any(
            query in str(value).casefold()
            for value in (
                module["classification"],
                *(release["channel"] for release in module["versions"]),
                *(release["version"] for release in module["versions"]),
            )
        ):
            bucket = 7
        else:
            return None
        return (bucket, module_id)

    def _publisher_summary(self, modules: list[dict[str, Any]]) -> PublisherSummary:
        publisher = modules[0]["publisher"]
        return PublisherSummary(
            id=publisher["id"],
            name=publisher["name"],
            classifications=sorted({module["classification"] for module in modules}),
            package_count=len(modules),
            release_count=sum(len(module["versions"]) for module in modules),
        )
