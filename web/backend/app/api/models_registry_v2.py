"""Registry v2 read DTOs; independent of optional database dependencies."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from web.backend.app.models import ApiModel, Channel, Classification, Publisher


class ChannelTarget(ApiModel):
    """Current mutable channel pointer, not a historical publication label."""

    version: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModuleSummary(ApiModel):
    id: str
    name: str
    description: str | None
    publisher: Publisher
    classification: Classification
    license: str
    source_repository: str
    homepage: str | None
    documentation_url: str | None
    stable_version: str | None = Field(description="Explicit stable pointer; null if absent.")
    channels: dict[Channel, ChannelTarget]
    version_count: int = Field(ge=1)


class ModuleDetail(ModuleSummary):
    versions_url: str = Field(description="Paginated immutable published version history.")


class VersionArtifact(ApiModel):
    url: str = Field(description="Preserved artifact_original_url, including historical v1 URLs.")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int | None = Field(ge=0)
    storage_locator: str | None


class VersionSource(ApiModel):
    repository: str
    tag: str | None
    commit: str


class VersionCompatibility(ApiModel):
    host: str
    sdk: str


class VersionProvenance(ApiModel):
    """Unknown historical evidence is null, including reproducible; null never means false."""

    builder_version: str | None = None
    builder_commit: str | None = None
    host_commit: str | None = None
    reproducible: bool | None = None
    host_contract_status: Literal["passed", "failed"] | None = None
    environment: dict[str, Any] | None = None


class PublishedVersion(ApiModel):
    """Immutable published version binding; channel movement does not rewrite this record."""

    module_id: str
    version: str
    historical_publication_channel: Channel = Field(
        description="Label at publication, distinct from today's module_channels pointers."
    )
    bundle_format_version: int
    artifact: VersionArtifact
    source: VersionSource
    compatibility: VersionCompatibility
    dependencies: dict[str, str] = Field(description="Exact stored specifiers; no resolution.")
    published_at: datetime | None
    provenance: VersionProvenance


class RegistryPage[T](ApiModel):
    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ModulePage(RegistryPage[ModuleSummary]):
    pass


class VersionPage(RegistryPage[PublishedVersion]):
    pass


class ModuleSearch(ModulePage):
    query: str


class RegistryPublisher(Publisher):
    module_count: int = Field(ge=1)


class PublisherPage(RegistryPage[RegistryPublisher]):
    pass


class RegistryPublisherDetail(RegistryPublisher):
    modules: ModulePage


class Liveness(ApiModel):
    status: Literal["ok"] = "ok"


class Readiness(ApiModel):
    status: Literal["ok"] = "ok"
    source: Literal["postgresql"] = "postgresql"
    schema_revision: str


class RegistryError(ApiModel):
    detail: str
