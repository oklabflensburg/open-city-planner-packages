"""Pydantic v2 API contracts derived from Registry v1 metadata."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Classification = Literal["first-party", "reviewed-community"]
Channel = Literal["stable", "beta", "nightly"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Publisher(ApiModel):
    id: str
    name: str


class Compatibility(ApiModel):
    host: str
    sdk: str
    modules: dict[str, str]


class Artifact(ApiModel):
    url: HttpUrl
    sha256: str


class PackageRelease(ApiModel):
    version: str
    channel: Channel
    artifact: Artifact
    bundle_format_version: int
    source_commit: str
    source_tag: str | None = None
    requires: Compatibility


class PackageSummary(ApiModel):
    id: str
    name: str
    description: str | None = None
    publisher: Publisher
    classification: Classification
    latest_version: str
    latest_channel: Channel
    compatibility: Compatibility
    channels: list[Channel]


class PackageDetail(PackageSummary):
    source_repository: HttpUrl
    license: str
    homepage: HttpUrl | None = None
    documentation_url: HttpUrl | None = None
    versions: list[PackageRelease]


class PackagePage(ApiModel):
    items: list[PackageSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class SearchResult(PackagePage):
    query: str


class PublisherSummary(ApiModel):
    id: str
    name: str
    classifications: list[Classification]
    package_count: int = Field(ge=0)
    release_count: int = Field(ge=0)


class PublisherDetail(PublisherSummary):
    packages: list[PackageSummary]


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    registry_schema: Literal[1] = 1
    packages: int = Field(ge=0)
