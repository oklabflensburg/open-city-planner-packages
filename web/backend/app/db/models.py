"""Relational Registry v2 metadata. No artifact bytes and no publication side effects."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Created:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Updated:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Publisher(Created, Updated, Base):
    __tablename__ = "publishers"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint("btrim(id) <> '' AND btrim(name) <> ''", name="identity"),)


class Module(Created, Updated, Base):
    __tablename__ = "modules"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    homepage: Mapped[str | None] = mapped_column(Text)
    documentation_url: Mapped[str | None] = mapped_column(Text)
    publisher_id: Mapped[str] = mapped_column(ForeignKey("publishers.id", ondelete="RESTRICT"))
    classification: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    source_repository: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("id ~ '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'", name="module_id"),
        CheckConstraint(
            "classification IN ('first-party', 'reviewed-community')", name="classification"
        ),
        CheckConstraint("btrim(source_repository) <> ''", name="source_repository"),
        CheckConstraint("btrim(name) <> '' AND btrim(license) <> ''", name="display"),
    )


class Artifact(Created, Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    digest_algorithm: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    storage_locator: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("digest_algorithm", "digest"),
        CheckConstraint("digest_algorithm = 'sha256'", name="digest_algorithm"),
        CheckConstraint("digest ~ '^[0-9a-f]{64}$'", name="digest"),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="byte_size"),
        CheckConstraint("storage_locator IS NULL OR btrim(storage_locator) <> ''", name="locator"),
    )


class BuildProvenance(Created, Base):
    __tablename__ = "build_provenance"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_repository: Mapped[str] = mapped_column(Text)
    source_tag: Mapped[str | None] = mapped_column(Text)
    source_commit: Mapped[str] = mapped_column(Text)
    builder_version: Mapped[str | None] = mapped_column(Text)
    builder_commit: Mapped[str | None] = mapped_column(Text)
    host_commit: Mapped[str | None] = mapped_column(Text)
    reproducible: Mapped[bool | None]
    host_contract_status: Mapped[str | None] = mapped_column(Text)
    # Supplementary evidence only; registry identities/relations remain normal columns.
    environment_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("btrim(source_repository) <> ''", name="source_repository"),
        CheckConstraint("source_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'", name="source_commit"),
        CheckConstraint(
            "host_contract_status IS NULL OR host_contract_status IN ('passed', 'failed')",
            name="host_contract_status",
        ),
    )


class ModuleVersion(Base):
    __tablename__ = "module_versions"
    module_id: Mapped[str] = mapped_column(
        ForeignKey("modules.id", ondelete="RESTRICT"), primary_key=True
    )
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    # Original v1 URL belongs to the version binding, not a deduplicated digest object.
    artifact_original_url: Mapped[str] = mapped_column(Text)
    # Retain v1 tie ordering for SemVer build-metadata variants.
    historical_order: Mapped[int]
    build_provenance_id: Mapped[int | None] = mapped_column(
        ForeignKey("build_provenance.id", ondelete="RESTRICT")
    )
    bundle_format_version: Mapped[int]
    source_tag: Mapped[str | None] = mapped_column(Text)
    source_commit: Mapped[str] = mapped_column(Text)
    host_compatibility: Mapped[str] = mapped_column(Text)
    sdk_compatibility: Mapped[str] = mapped_column(Text)
    historical_publication_channel: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint("btrim(version) <> ''", name="version"),
        CheckConstraint("historical_order >= 0", name="historical_order"),
        CheckConstraint("bundle_format_version = 1", name="bundle_format"),
        CheckConstraint("source_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'", name="source_commit"),
        CheckConstraint("btrim(artifact_original_url) <> ''", name="artifact_url"),
        CheckConstraint(
            "btrim(host_compatibility) <> '' AND btrim(sdk_compatibility) <> ''",
            name="compatibility",
        ),
        CheckConstraint(
            "historical_publication_channel IN ('stable', 'beta', 'nightly')", name="channel"
        ),
        CheckConstraint(
            "historical_publication_channel <> 'stable' OR split_part(version, '+', 1) !~ '-'",
            name="stable",
        ),
    )


class ModuleChannel(Updated, Base):
    __tablename__ = "module_channels"
    module_id: Mapped[str] = mapped_column(Text, primary_key=True)
    channel: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(BigInteger, server_default="1")
    __table_args__ = (
        ForeignKeyConstraint(
            ["module_id", "version"],
            ["module_versions.module_id", "module_versions.version"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("channel IN ('stable', 'beta', 'nightly')", name="channel"),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint("channel <> 'stable' OR split_part(version, '+', 1) !~ '-'", name="stable"),
    )


class ModuleDependency(Base):
    __tablename__ = "module_dependencies"
    owner_module_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_version: Mapped[str] = mapped_column(Text, primary_key=True)
    dependency_module_id: Mapped[str] = mapped_column(
        ForeignKey("modules.id", ondelete="RESTRICT"), primary_key=True
    )
    specifier: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_module_id", "owner_version"],
            ["module_versions.module_id", "module_versions.version"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("btrim(specifier) <> ''", name="specifier"),
        CheckConstraint("owner_module_id <> dependency_module_id", name="not_self"),
    )


class PromotionEvent(Base):
    __tablename__ = "promotion_events"
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    module_id: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text)
    candidate_digest: Mapped[str] = mapped_column(Text)
    approval_reference: Mapped[str] = mapped_column(Text)
    approval_identity: Mapped[str] = mapped_column(Text)
    previous_channel_version: Mapped[str | None] = mapped_column(Text)
    new_channel_version: Mapped[str] = mapped_column(Text)
    intent: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["module_id", "version"],
            ["module_versions.module_id", "module_versions.version"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("module_id", "version"),
        CheckConstraint("channel IN ('stable', 'beta', 'nightly')", name="channel"),
        CheckConstraint("candidate_digest ~ '^[0-9a-f]{64}$'", name="candidate_digest"),
        CheckConstraint("new_channel_version = version", name="target"),
    )


class ImmutableRecordError(ValueError):
    """An application attempted to rewrite published history."""


@event.listens_for(Session, "before_flush")
def protect_history(session: Session, flush_context: object, instances: object) -> None:
    """ORM guard; privileged SQL is not a supported registry write interface."""
    immutable = (ModuleVersion, ModuleDependency, BuildProvenance, PromotionEvent)
    for obj in session.deleted:
        if isinstance(obj, (*immutable, Artifact)):
            raise ImmutableRecordError(
                "Published metadata/evidence cannot be deleted through the ORM"
            )
    for obj in session.dirty:
        changed = {attr.key for attr in inspect(obj).attrs if attr.history.has_changes()}
        if isinstance(obj, immutable) and changed:
            raise ImmutableRecordError("Published metadata/evidence is immutable")
        protected = set()
        if isinstance(obj, Artifact):
            protected = {"id", "digest_algorithm", "digest", "created_at"}
        elif isinstance(obj, Module):
            protected = {"id", "publisher_id", "classification", "license", "source_repository"}
        elif isinstance(obj, Publisher):
            protected = {"id"}
        if changed & protected:
            raise ImmutableRecordError("Protected registry identity/provenance is immutable")
