"""Migration, integrity, concurrency and lossless import contracts on PostgreSQL."""

import copy
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import delete, insert, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scripts.registry import build_index, canonical_json, canonical_module, load_registry
from web.backend.app.db.config import database_url
from web.backend.app.db.models import (
    Artifact,
    Base,
    BuildProvenance,
    ImmutableRecordError,
    Module,
    ModuleChannel,
    ModuleDependency,
    ModuleVersion,
    Publisher,
)
from web.backend.app.db.repository import RegistryConflict, RegistryDatabaseRepository
from web.backend.app.registry_import_v1 import import_registry
from web.backend.db_tests.conftest import ROOT, migration_config

SOURCE = ROOT / "registry"


def snapshot(engine):
    with engine.connect() as connection:
        return {
            table.name: connection.execute(select(table).order_by(*table.primary_key)).all()
            for table in Base.metadata.sorted_tables
        }


@pytest.fixture
def populated(pg_engine):
    import_registry(pg_engine, SOURCE)
    return pg_engine


@pytest.fixture
def copied_source(tmp_path):
    shutil.copytree(SOURCE, tmp_path / "registry")
    return tmp_path / "registry"


def write_module(root, module):
    (root / "modules" / f"{module['id']}.json").write_text(canonical_json(module))


def test_migration_roundtrip_and_metadata(pg_engine):
    with pg_engine.begin() as connection:
        assert connection.dialect.name == "postgresql"
        assert connection.scalar(text("SHOW server_version"))
        assert set(Base.metadata.tables) <= set(inspect(connection).get_table_names())
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        command.downgrade(migration_config(connection), "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(migration_config(connection), "head")
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    assert import_registry(pg_engine, SOURCE)["v1_parity"]


def test_real_source_parity_counts_channels_and_unknowns(pg_engine):
    modules = load_registry(SOURCE)
    report = import_registry(pg_engine, SOURCE)
    expected_versions = sum(len(m["versions"]) for m in modules)
    assert report["counts"] == {
        "publishers": len({m["publisher"]["id"] for m in modules}),
        "modules": len(modules),
        "module_versions": expected_versions,
        "build_provenance": expected_versions,
        "artifacts": len({v["artifact"]["sha256"] for m in modules for v in m["versions"]}),
        "module_dependencies": sum(
            len(v["requires"]["modules"]) for m in modules for v in m["versions"]
        ),
        "module_channels": sum(len(m["channels"]) for m in build_index(modules)["modules"]),
    }
    with Session(pg_engine) as session:
        repo = RegistryDatabaseRepository(session)
        projection = repo.project_v1()
        for source, actual in zip(modules, projection, strict=True):
            assert canonical_json(canonical_module(source)) == canonical_json(actual)
            assert (
                canonical_json(actual)
                == (ROOT / "dist/modules" / f"{source['id']}.json").read_text()
            )
        assert canonical_json(build_index(projection)) == (ROOT / "dist/index.json").read_text()
        expected_channels = {m["id"]: m["channels"] for m in build_index(modules)["modules"]}
        assert repo.channel_targets() == expected_channels == report["channels"]
        assert {
            m: {c: v["version"] for c, v in targets.items()}
            for m, targets in expected_channels.items()
        } == {
            "analysis-areas": {"stable": "1.5.3"},
            "search": {"beta": "0.1.0"},
            "statistics": {"stable": "0.3.0"},
        }
        candidate = json.loads((ROOT / "candidates/statistics/0.4.0/provenance.json").read_text())
        assert session.get(ModuleVersion, (candidate["module_id"], candidate["version"])) is None
        for version in session.scalars(select(ModuleVersion)):
            assert version.published_at is None
            assert version.imported_at is not None
        for evidence in session.scalars(select(BuildProvenance)):
            assert all(
                getattr(evidence, field) is None
                for field in (
                    "builder_version",
                    "builder_commit",
                    "host_commit",
                    "reproducible",
                    "host_contract_status",
                    "environment_json",
                )
            )
            assert evidence.source_commit and evidence.imported_at
        for artifact in session.scalars(select(Artifact)):
            assert artifact.storage_locator is None and artifact.byte_size is None


def test_idempotent_import_preserves_every_row_and_timestamp(populated):
    before = snapshot(populated)
    assert import_registry(populated, SOURCE)["inserted_versions"] == 0
    assert snapshot(populated) == before


@pytest.mark.parametrize(
    "field",
    [
        "digest",
        "commit",
        "tag",
        "dependency",
        "channel",
        "host",
        "sdk",
        "url",
        "license",
        "publisher",
        "name",
    ],
)
def test_conflicting_source_rolls_back_everything(populated, copied_source, field):
    modules = load_registry(copied_source)
    module = next(m for m in modules if m["id"] == "analysis-areas")
    release = module["versions"][-1]
    if field == "digest":
        release["artifact"]["sha256"] = "a" * 64
    elif field == "commit":
        release["source_commit"] = "a" * 40
    elif field == "tag":
        release["source_tag"] = "different-tag"
    elif field == "dependency":
        release["requires"]["modules"]["statistics"] = ">=0.3.0,<1.0.0"
    elif field == "channel":
        release["channel"] = "beta"
    elif field in {"host", "sdk"}:
        release["requires"][field] = ">=0.1.0,<2.0.0"
    elif field == "url":
        release["artifact"]["url"] = (
            "https://packages.stadtplaner.oklabflensburg.de/modules/analysis-areas/"
            "1.5.3/analysis-areas-1.5.3.ocp"
        )
    elif field == "license":
        module["license"] = "MIT"
    elif field == "publisher":
        module["publisher"]["id"] = "different-publisher"
    else:
        module["name"] = "Different display name"
    write_module(copied_source, module)
    before = snapshot(populated)
    with pytest.raises(RegistryConflict):
        import_registry(populated, copied_source)
    assert snapshot(populated) == before


def test_partial_import_failure_leaves_no_rows(pg_engine, copied_source):
    module = next(m for m in load_registry(copied_source) if m["id"] == "statistics")
    module["versions"][-1]["requires"]["modules"] = {"missing-module": ">=1.0.0"}
    write_module(copied_source, module)
    before = snapshot(pg_engine)
    with pytest.raises(RegistryConflict, match="Missing dependency"):
        import_registry(pg_engine, copied_source)
    assert snapshot(pg_engine) == before


def test_invalid_source_is_rejected_before_writing(pg_engine, copied_source):
    (copied_source / "registry.json").write_text('{"schema_version": 9}')
    before = snapshot(pg_engine)
    with pytest.raises(ValueError, match="schema_version"):
        import_registry(pg_engine, copied_source)
    assert snapshot(pg_engine) == before


def test_missing_published_source_record_is_conflict(populated, copied_source):
    (copied_source / "modules/search.json").unlink()
    with pytest.raises(RegistryConflict, match="projection"):
        import_registry(populated, copied_source)


def test_conflicting_channel_is_not_repaired(populated):
    with populated.begin() as connection:
        connection.execute(
            update(ModuleChannel)
            .where(ModuleChannel.module_id == "statistics")
            .values(version="0.2.0", revision=2)
        )
    before = snapshot(populated)
    with pytest.raises(RegistryConflict, match="module_channels"):
        import_registry(populated, SOURCE)
    assert snapshot(populated) == before


def test_optional_fields_and_exact_semver_survive_import(pg_engine, copied_source):
    module = next(m for m in load_registry(copied_source) if m["id"] == "search")
    module.pop("description", None)
    module["homepage"] = "https://example.org/"
    module["documentation_url"] = "https://example.org/docs"
    for number, version in enumerate(("0.5.0-beta.1", "0.5.0+build-one"), start=1):
        release = copy.deepcopy(module["versions"][0])
        release["version"] = version
        release["channel"] = "beta" if number == 1 else "stable"
        release.pop("source_tag")
        release["artifact"] = {
            "url": f"https://packages.stadtplaner.oklabflensburg.de/modules/search/"
            f"{version}/search-{version}.ocp",
            "sha256": str(number) * 64,
        }
        module["versions"].append(release)
    write_module(copied_source, module)
    import_registry(pg_engine, copied_source)
    with Session(pg_engine) as session:
        result = next(
            m for m in RegistryDatabaseRepository(session).project_v1() if m["id"] == "search"
        )
        assert canonical_json(result) == canonical_json(canonical_module(module))


@pytest.mark.parametrize(
    "table,changes",
    [
        (Module, {"publisher_id": "absent"}),
        (ModuleVersion, {"artifact_id": -1}),
        (ModuleVersion, {"build_provenance_id": -1}),
        (ModuleVersion, {"module_id": "absent"}),
        (ModuleChannel, {"module_id": "search", "version": "1.5.3"}),
        (ModuleDependency, {"dependency_module_id": "absent"}),
        (ModuleDependency, {"owner_version": "999.0.0"}),
    ],
)
def test_database_foreign_keys(populated, table, changes):
    with populated.connect() as connection:
        row = dict(connection.execute(select(table.__table__)).mappings().first())
    with pytest.raises(IntegrityError) as error, populated.begin() as connection:
        connection.execute(
            update(table)
            .where(*(column == row[column.name] for column in table.__table__.primary_key))
            .values(**changes)
        )
    assert error.value.orig.sqlstate in {"23503", "23001"}


@pytest.mark.parametrize(
    "table", [Publisher, Module, Artifact, ModuleVersion, ModuleChannel, ModuleDependency]
)
def test_database_unique_identities(populated, table):
    with populated.connect() as connection:
        row = dict(connection.execute(select(table.__table__)).mappings().first())
    if table is Artifact:
        row.pop("id")  # Assert digest uniqueness independently of the surrogate PK.
    with pytest.raises(IntegrityError) as error, populated.begin() as connection:
        connection.execute(insert(table).values(**row))
    assert error.value.orig.sqlstate == "23505"


@pytest.mark.parametrize("table", [Publisher, Module, Artifact, BuildProvenance, ModuleVersion])
def test_database_delete_restrict(populated, table):
    with pytest.raises(IntegrityError) as error, populated.begin() as connection:
        connection.execute(delete(table))
    assert error.value.orig.sqlstate in {"23503", "23001"}


def test_dependency_alone_prevents_version_deletion(populated):
    with populated.begin() as connection:
        connection.execute(delete(ModuleChannel))
    with pytest.raises(IntegrityError) as error, populated.begin() as connection:
        connection.execute(
            delete(ModuleVersion).where(
                ModuleVersion.module_id == "analysis-areas", ModuleVersion.version == "1.5.2"
            )
        )
    assert error.value.orig.sqlstate in {"23503", "23001"}


@pytest.mark.parametrize(
    "table,changes",
    [
        (Artifact, {"digest": "not-a-digest"}),
        (Artifact, {"digest_algorithm": "sha1"}),
        (Artifact, {"byte_size": -1}),
        (Module, {"classification": "trusted-superuser"}),
        (Module, {"source_repository": " "}),
        (ModuleChannel, {"channel": "latest"}),
        (ModuleChannel, {"revision": 0}),
        (ModuleVersion, {"historical_publication_channel": "latest"}),
        (ModuleVersion, {"bundle_format_version": 2}),
    ],
)
def test_database_checks(populated, table, changes):
    with pytest.raises(IntegrityError) as error, populated.begin() as connection:
        connection.execute(update(table).values(**changes))
    assert error.value.orig.sqlstate == "23514"


@pytest.mark.parametrize(
    "model,field,value",
    [
        (ModuleVersion, "source_commit", "b" * 40),
        (ModuleVersion, "bundle_format_version", 2),
        (ModuleDependency, "specifier", ">=0.3.0"),
        (BuildProvenance, "reproducible", False),
        (Artifact, "digest", "b" * 64),
        (Module, "license", "MIT"),
        (Module, "publisher_id", "someone-else"),
        (Publisher, "id", "someone-else"),
    ],
)
def test_orm_rejects_history_edits(populated, model, field, value):
    with pytest.raises(ImmutableRecordError), Session(populated) as session, session.begin():
        record = session.scalars(select(model)).first()
        setattr(record, field, value)
        session.flush()


@pytest.mark.parametrize("model", [ModuleVersion, ModuleDependency, BuildProvenance, Artifact])
def test_orm_rejects_history_deletes(populated, model):
    with pytest.raises(ImmutableRecordError), Session(populated) as session, session.begin():
        session.delete(session.scalars(select(model)).first())
        session.flush()


def test_repository_idempotency_and_dependencies(populated):
    module = next(m for m in load_registry(SOURCE) if m["id"] == "analysis-areas")
    release = module["versions"][-1]
    before = snapshot(populated)
    with Session(populated) as session, session.begin():
        assert (
            RegistryDatabaseRepository(session).insert_published_version(module["id"], release)
            is False
        )
    assert snapshot(populated) == before
    altered = copy.deepcopy(release)
    altered["requires"]["modules"] = {}
    with pytest.raises(RegistryConflict), Session(populated) as session, session.begin():
        RegistryDatabaseRepository(session).insert_published_version(module["id"], altered)


def next_search_release():
    source = next(m for m in load_registry(SOURCE) if m["id"] == "search")
    release = copy.deepcopy(source["versions"][0])
    release.update(version="0.2.0", source_tag="v0.2.0")
    release["artifact"] = {
        "url": "https://packages.stadtplaner.oklabflensburg.de/modules/search/0.2.0/search-0.2.0.ocp",
        "sha256": "c" * 64,
    }
    return release


@pytest.mark.parametrize("conflict", [False, True])
def test_concurrent_version_inserts_serialize(populated, conflict):
    release = next_search_release()
    inserted = Event()
    competing = Event()
    allow_commit = Event()
    competing_pid = []

    def first():
        with Session(populated) as session, session.begin():
            result = RegistryDatabaseRepository(session).insert_published_version("search", release)
            inserted.set()
            assert allow_commit.wait(5)
        return result

    def second():
        assert inserted.wait(5)
        other = copy.deepcopy(release)
        if conflict:
            other["artifact"]["sha256"] = "d" * 64
        with Session(populated) as session, session.begin():
            competing_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            competing.set()
            return RegistryDatabaseRepository(session).insert_published_version("search", other)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(first)
        second_result = pool.submit(second)
        try:
            assert competing.wait(5)
            deadline = monotonic() + 3
            with populated.connect() as observer:
                while monotonic() < deadline:
                    blocked = observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"),
                        {"pid": competing_pid[0]},
                    )
                    if blocked:
                        break
                    Event().wait(0.01)
                assert blocked, "Competing insert must wait for the uncommitted version"
        finally:
            allow_commit.set()
        assert first_result.result(timeout=10) is True
        if conflict:
            with pytest.raises(RegistryConflict):
                second_result.result(timeout=10)
        else:
            assert second_result.result(timeout=10) is False
    with Session(populated) as session:
        repo = RegistryDatabaseRepository(session)
        version = session.get(ModuleVersion, ("search", "0.2.0"))
        assert repo.release_structure(version) == release
        # Inserting metadata is deliberately not channel promotion.
        assert repo.channel_targets()["search"]["beta"]["version"] == "0.1.0"


@pytest.mark.parametrize(
    "value",
    [
        "sqlite:///:memory:",
        "postgresql://localhost/db",
        "postgresql+psycopg://localhost",
        "broken-secret-url",
    ],
)
def test_database_configuration_rejects_unsupported_urls(value):
    with pytest.raises(ValueError) as error:
        database_url(value)
    assert value not in str(error.value)


def test_semver_precedence_ties_preserve_v1_order(pg_engine, copied_source):
    module = next(m for m in load_registry(copied_source) if m["id"] == "search")
    original = module["versions"][0]
    module["versions"] = []
    for position, version in enumerate(("0.5.0+z", "0.5.0+a"), start=1):
        release = copy.deepcopy(original)
        release.update(version=version, source_tag=f"v{version}")
        release["artifact"] = {
            "url": f"https://packages.stadtplaner.oklabflensburg.de/modules/search/"
            f"{version}/search-{version}.ocp",
            "sha256": str(position) * 64,
        }
        module["versions"].append(release)
    write_module(copied_source, module)
    report = import_registry(pg_engine, copied_source)
    assert report["channels"]["search"]["beta"]["version"] == "0.5.0+z"
    with Session(pg_engine) as session:
        actual = next(
            m for m in RegistryDatabaseRepository(session).project_v1() if m["id"] == "search"
        )
        assert canonical_json(actual) == canonical_json(canonical_module(module))
    assert import_registry(pg_engine, copied_source)["inserted_versions"] == 0


def test_channel_transaction_rolls_back_revision_and_target(populated):
    before = snapshot(populated)
    with pytest.raises(RuntimeError), Session(populated) as session, session.begin():
        channel = session.get(ModuleChannel, ("statistics", "stable"), with_for_update=True)
        channel.version = "0.2.0"
        channel.revision += 1
        session.flush()
        raise RuntimeError("abort the transaction")
    assert snapshot(populated) == before


def test_inconsistent_publisher_names_fail_without_merging(pg_engine, copied_source):
    module = next(m for m in load_registry(copied_source) if m["id"] == "statistics")
    module["publisher"]["name"] = "Conflicting publisher name"
    write_module(copied_source, module)
    before = snapshot(pg_engine)
    with pytest.raises(RegistryConflict, match="publishers"):
        import_registry(pg_engine, copied_source)
    assert snapshot(pg_engine) == before


def test_import_does_not_touch_sequences_on_identical_retry(populated):
    def sequences():
        with populated.connect() as connection:
            return connection.execute(
                text(
                    "SELECT sequencename, last_value FROM pg_sequences "
                    "WHERE schemaname = current_schema() ORDER BY sequencename"
                )
            ).all()

    before = sequences()
    import_registry(populated, SOURCE)
    assert sequences() == before
