"""create relational Registry v2 shadow schema

Revision ID: 0045_registry_v2
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0045_registry_v2"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("digest_algorithm", sa.Text(), nullable=False),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("storage_locator", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_artifacts_digest")),
        sa.CheckConstraint(
            "digest_algorithm = 'sha256'", name=op.f("ck_artifacts_digest_algorithm")
        ),
        sa.CheckConstraint(
            "storage_locator IS NULL OR btrim(storage_locator) <> ''",
            name=op.f("ck_artifacts_locator"),
        ),
        sa.CheckConstraint(
            "byte_size IS NULL OR byte_size >= 0", name=op.f("ck_artifacts_byte_size")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint(
            "digest_algorithm", "digest", name=op.f("uq_artifacts_digest_algorithm")
        ),
    )
    op.create_table(
        "build_provenance",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_repository", sa.Text(), nullable=False),
        sa.Column("source_tag", sa.Text(), nullable=True),
        sa.Column("source_commit", sa.Text(), nullable=False),
        sa.Column("builder_version", sa.Text(), nullable=True),
        sa.Column("builder_commit", sa.Text(), nullable=True),
        sa.Column("host_commit", sa.Text(), nullable=True),
        sa.Column("reproducible", sa.Boolean(), nullable=True),
        sa.Column("host_contract_status", sa.Text(), nullable=True),
        sa.Column("environment_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(source_repository) <> ''", name=op.f("ck_build_provenance_source_repository")
        ),
        sa.CheckConstraint(
            "host_contract_status IS NULL OR host_contract_status IN ('passed', 'failed')",
            name=op.f("ck_build_provenance_host_contract_status"),
        ),
        sa.CheckConstraint(
            "source_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'",
            name=op.f("ck_build_provenance_source_commit"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_build_provenance")),
    )
    op.create_table(
        "publishers",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(id) <> '' AND btrim(name) <> ''", name=op.f("ck_publishers_identity")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publishers")),
    )
    op.create_table(
        "modules",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("homepage", sa.Text(), nullable=True),
        sa.Column("documentation_url", sa.Text(), nullable=True),
        sa.Column("publisher_id", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column("source_repository", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(name) <> '' AND btrim(license) <> ''", name=op.f("ck_modules_display")
        ),
        sa.CheckConstraint(
            "btrim(source_repository) <> ''", name=op.f("ck_modules_source_repository")
        ),
        sa.CheckConstraint(
            "classification IN ('first-party', 'reviewed-community')",
            name=op.f("ck_modules_classification"),
        ),
        sa.CheckConstraint(
            "id ~ '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'", name=op.f("ck_modules_module_id")
        ),
        sa.ForeignKeyConstraint(
            ["publisher_id"],
            ["publishers.id"],
            name=op.f("fk_modules_publisher_id_publishers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modules")),
    )
    op.create_table(
        "module_versions",
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("artifact_original_url", sa.Text(), nullable=False),
        sa.Column("historical_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "historical_order >= 0", name=op.f("ck_module_versions_historical_order")
        ),
        sa.Column("build_provenance_id", sa.BigInteger(), nullable=True),
        sa.Column("bundle_format_version", sa.Integer(), nullable=False),
        sa.Column("source_tag", sa.Text(), nullable=True),
        sa.Column("source_commit", sa.Text(), nullable=False),
        sa.Column("host_compatibility", sa.Text(), nullable=False),
        sa.Column("sdk_compatibility", sa.Text(), nullable=False),
        sa.Column("historical_publication_channel", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(artifact_original_url) <> ''", name=op.f("ck_module_versions_artifact_url")
        ),
        sa.CheckConstraint(
            "btrim(host_compatibility) <> '' AND btrim(sdk_compatibility) <> ''",
            name=op.f("ck_module_versions_compatibility"),
        ),
        sa.CheckConstraint("btrim(version) <> ''", name=op.f("ck_module_versions_version")),
        sa.CheckConstraint(
            "historical_publication_channel <> 'stable' OR split_part(version, '+', 1) !~ '-'",
            name=op.f("ck_module_versions_stable"),
        ),
        sa.CheckConstraint(
            "historical_publication_channel IN ('stable', 'beta', 'nightly')",
            name=op.f("ck_module_versions_channel"),
        ),
        sa.CheckConstraint(
            "source_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'",
            name=op.f("ck_module_versions_source_commit"),
        ),
        sa.CheckConstraint(
            "bundle_format_version = 1", name=op.f("ck_module_versions_bundle_format")
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_module_versions_artifact_id_artifacts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["build_provenance_id"],
            ["build_provenance.id"],
            name=op.f("fk_module_versions_build_provenance_id_build_provenance"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["modules.id"],
            name=op.f("fk_module_versions_module_id_modules"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("module_id", "version", name=op.f("pk_module_versions")),
    )
    op.create_table(
        "module_channels",
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("revision", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel <> 'stable' OR split_part(version, '+', 1) !~ '-'",
            name=op.f("ck_module_channels_stable"),
        ),
        sa.CheckConstraint(
            "channel IN ('stable', 'beta', 'nightly')", name=op.f("ck_module_channels_channel")
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_module_channels_revision")),
        sa.ForeignKeyConstraint(
            ["module_id", "version"],
            ["module_versions.module_id", "module_versions.version"],
            name=op.f("fk_module_channels_module_id_module_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("module_id", "channel", name=op.f("pk_module_channels")),
    )
    op.create_table(
        "module_dependencies",
        sa.Column("owner_module_id", sa.Text(), nullable=False),
        sa.Column("owner_version", sa.Text(), nullable=False),
        sa.Column("dependency_module_id", sa.Text(), nullable=False),
        sa.Column("specifier", sa.Text(), nullable=False),
        sa.CheckConstraint("btrim(specifier) <> ''", name=op.f("ck_module_dependencies_specifier")),
        sa.CheckConstraint(
            "owner_module_id <> dependency_module_id", name=op.f("ck_module_dependencies_not_self")
        ),
        sa.ForeignKeyConstraint(
            ["dependency_module_id"],
            ["modules.id"],
            name=op.f("fk_module_dependencies_dependency_module_id_modules"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_module_id", "owner_version"],
            ["module_versions.module_id", "module_versions.version"],
            name=op.f("fk_module_dependencies_owner_module_id_module_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "owner_module_id",
            "owner_version",
            "dependency_module_id",
            name=op.f("pk_module_dependencies"),
        ),
    )


def downgrade() -> None:
    op.drop_table("module_dependencies")
    op.drop_table("module_channels")
    op.drop_table("module_versions")
    op.drop_table("modules")
    op.drop_table("publishers")
    op.drop_table("build_provenance")
    op.drop_table("artifacts")
