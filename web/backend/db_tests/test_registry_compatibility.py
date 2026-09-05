"""V1 contracts over real migrated PostgreSQL; no production service or artifact access."""

import copy
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scripts.registry import canonical_json
from web.backend.app.api.registry_compatibility import RegistryCompatibilityService
from web.backend.app.api.registry_v2 import read_repository
from web.backend.app.db.models import (
    Artifact,
    BuildProvenance,
    Module,
    ModuleChannel,
    ModuleVersion,
)
from web.backend.app.db.repository import RegistryDatabaseRepository
from web.backend.app.main import create_app
from web.backend.app.registry_import_v1 import import_registry
from web.backend.db_tests.conftest import ROOT


@pytest.fixture
def compat_engine(pg_engine):
    import_registry(pg_engine, ROOT / "registry")
    return pg_engine


@pytest.fixture
def client(compat_engine):
    with TestClient(
        create_app(v2_enabled=True, v1_compat_enabled=True, engine_factory=lambda: compat_engine)
    ) as client:
        yield client


def test_all_committed_bytes_and_closed_contract(client):
    index = client.get("/index.json")
    assert index.status_code == 200
    assert index.content == (ROOT / "dist/index.json").read_bytes()
    assert index.json()["schema_version"] == 1
    expected = {
        "analysis-areas": ("stable", "1.5.3"),
        "search": ("beta", "0.1.0"),
        "statistics": ("stable", "0.3.0"),
    }
    for entry in index.json()["modules"]:
        channel, version = expected[entry["id"]]
        assert entry["channels"][channel]["version"] == version
        response = client.get(entry["metadata"])
        assert response.status_code == 200
        assert response.content == (ROOT / "dist" / entry["metadata"].lstrip("/")).read_bytes()
        assert response.content.endswith(b"\n")
        assert response.headers["content-type"] == "application/json"
        assert not any(
            key in response.text
            for key in (
                '"storage_locator"',
                '"published_at"',
                '"module_channels"',
                '"builder_version"',
                '"reproducible"',
                '"historical_order"',
                '"build_provenance_id"',
            )
        )
    assert [v["version"] for v in client.get("/modules/statistics.json").json()["versions"]] == [
        "0.2.0",
        "0.3.0",
    ]


@pytest.mark.parametrize("path", ["/index.json", "/modules/statistics.json"])
def test_etag_revalidation(client, path):
    response = client.get(path)
    etag = '"' + sha256(response.content).hexdigest() + '"'
    assert response.headers["etag"] == etag
    assert response.headers["cache-control"] == "no-cache"
    for validator in (etag, "W/" + etag, '"other", W/' + etag, "*"):
        unchanged = client.get(path, headers={"If-None-Match": validator})
        assert unchanged.status_code == 304
        assert unchanged.content == b""
        assert unchanged.headers["etag"] == etag
        assert unchanged.headers["cache-control"] == "no-cache"
    assert client.get(path, headers={"If-None-Match": '"other"'}).status_code == 200
    assert client.get(path, headers={"Accept": "text/html"}).content == response.content


@pytest.mark.parametrize("case", ["rollback", "relabel", "multi-channel", "missing"])
def test_unrepresentable_channels_fail_closed(client, compat_engine, case):
    module_id = "statistics" if case in {"rollback", "missing"} else "search"
    previous = client.get("/index.json").headers["etag"]
    with Session(compat_engine) as session, session.begin():
        if case == "rollback":
            session.execute(
                update(ModuleChannel)
                .where(ModuleChannel.module_id == module_id)
                .values(version="0.2.0")
            )
        elif case == "missing":
            session.execute(delete(ModuleChannel).where(ModuleChannel.module_id == module_id))
        else:
            if case == "relabel":
                session.execute(delete(ModuleChannel).where(ModuleChannel.module_id == module_id))
            session.add(ModuleChannel(module_id=module_id, channel="stable", version="0.1.0"))
    for path in ("/index.json", f"/modules/{module_id}.json"):
        response = client.get(path, headers={"If-None-Match": previous})
        assert response.status_code == 503
        assert response.json() == {"detail": "Registry v1 compatibility verification failed"}
        assert "etag" not in response.headers
    # v2 can describe pointers independently; the compatibility guard must not change v2.
    assert client.get(f"/api/v1/modules/{module_id}/channels").status_code == 200


def test_new_published_version_and_pointer_visible_without_cache(client, compat_engine):
    paths = ["/index.json", "/modules/statistics.json"]
    old = {path: client.get(path).headers["etag"] for path in paths}
    # Synthetic future release in the isolated test DB; never the real 0.4.0 candidate.
    with Session(compat_engine) as session, session.begin():
        repo = RegistryDatabaseRepository(session)
        release = copy.deepcopy(repo.project_v1("statistics")[0]["versions"][-1])
        release["version"] = "0.5.0"
        release["artifact"]["url"] = (
            "https://packages.stadtplaner.oklabflensburg.de/modules/statistics/0.5.0/statistics-0.5.0.ocp"
        )
        repo.insert_published_version("statistics", release)
        session.execute(
            update(ModuleChannel)
            .where(ModuleChannel.module_id == "statistics")
            .values(version="0.5.0")
        )
    for path in paths:
        response = client.get(path, headers={"If-None-Match": old[path]})
        assert response.status_code == 200
        assert response.headers["etag"] != old[path]
        assert "0.5.0" in response.text
        assert "0.4.0" not in response.text


def test_candidate_evidence_and_internal_changes_do_not_leak(client, compat_engine):
    before = {path: client.get(path) for path in ("/index.json", "/modules/statistics.json")}
    with Session(compat_engine) as session, session.begin():
        session.add(Artifact(digest_algorithm="sha256", digest="f" * 64))
        session.add(
            BuildProvenance(
                source_repository="https://github.com/oklabflensburg/statistics",
                source_tag="v0.4.0",
                source_commit="f" * 40,
            )
        )
        session.execute(update(Artifact).values(storage_locator="internal/never-public"))
        publisher_id = session.get(Module, "statistics").publisher_id
        session.add(
            Module(
                id="candidate-only",
                name="Candidate",
                publisher_id=publisher_id,
                classification="first-party",
                license="MIT",
                source_repository="https://github.com/oklabflensburg/candidate",
            )
        )
    for path, previous in before.items():
        response = client.get(path)
        assert response.content == previous.content
        assert response.headers["etag"] == previous.headers["etag"]
    assert client.get("/modules/candidate-only.json").status_code == 404


def test_historical_order_is_preserved(client, compat_engine):
    with Session(compat_engine) as session, session.begin():
        session.execute(
            update(ModuleVersion)
            .where(ModuleVersion.module_id == "statistics", ModuleVersion.version == "0.2.0")
            .values(historical_order=9)
        )
    assert [v["version"] for v in client.get("/modules/statistics.json").json()["versions"]] == [
        "0.3.0",
        "0.2.0",
    ]
    assert client.get("/index.json").content == (ROOT / "dist/index.json").read_bytes()


@pytest.mark.parametrize(
    "path",
    [
        "/modules/nope.json",
        "/modules/UPPER.json",
        "/modules/a%5Cb.json",
        "/modules/a%2Fb.json",
        "/modules/%2e%2e%2findex.json",
        "/modules/" + "a" * 64 + ".json",
        "/modules/statistics/0.4.0/statistics-0.4.0.ocp",
    ],
)
def test_path_safety_and_no_artifact_handler(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_no_writes(client, method):
    for path in ("/index.json", "/modules/statistics.json"):
        assert client.request(method, path, json={}).status_code == 405


def test_outage_has_no_file_fallback_or_sensitive_diagnostics(client, compat_engine, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OperationalError("private SQL", {}, Exception("secret-password"))

    monkeypatch.setattr(compat_engine, "connect", unavailable)
    for path in ("/index.json", "/modules/statistics.json", "/ready"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Registry database unavailable"}
        assert response.headers["cache-control"] == "no-cache"
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/packages").status_code == 200


def test_schema_readiness(client, compat_engine):
    with compat_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'wrong'"))
    for path in ("/index.json", "/modules/statistics.json", "/ready"):
        assert client.get(path).status_code == 503


def test_bounded_queries_and_read_only_consistent_snapshot(compat_engine):
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(compat_engine, "before_cursor_execute", capture)
    try:
        with read_repository(compat_engine) as repository:
            assert (
                repository.session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            )
            assert repository.session.scalar(text("SHOW transaction_read_only")) == "on"
            statements.clear()
            service = RegistryCompatibilityService(repository)
            before = service.index()
            assert len(statements) == 4
            with compat_engine.begin() as writer:
                writer.execute(
                    update(Module).where(Module.id == "statistics").values(name="Changed")
                )
            assert service.index() == before
        with read_repository(compat_engine) as repository:
            assert RegistryCompatibilityService(repository).index() != before
    finally:
        event.remove(compat_engine, "before_cursor_execute", capture)


def test_compatibility_can_be_enabled_without_v2(compat_engine):
    with TestClient(
        create_app(v2_enabled=False, v1_compat_enabled=True, engine_factory=lambda: compat_engine)
    ) as client:
        assert client.get("/index.json").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.get("/api/v1/modules").status_code == 404
        assert client.get("/api/v1/packages").status_code == 200
        with read_repository(compat_engine) as repo:
            assert (
                canonical_json(RegistryCompatibilityService(repo).index()).encode()
                == (ROOT / "dist/index.json").read_bytes()
            )


def test_read_only_parity_preflight(compat_engine, tmp_path):
    import shutil

    from web.backend.app.registry_verify_v1 import verify

    assert verify(compat_engine, ROOT / "dist") == {
        "index_byte_parity": True,
        "module_byte_parity": 3,
        "published_versions": 6,
        "representable": True,
        "schema_revision": "0049_promotions",
    }
    dist = tmp_path / "dist"
    shutil.copytree(ROOT / "dist", dist)
    (dist / "index.json").write_text("{}")
    with pytest.raises(ValueError, match="Byte parity"):
        verify(compat_engine, dist)
    (dist / "modules/extra.json").write_text("{}")
    with pytest.raises(ValueError, match="file set"):
        verify(compat_engine, dist)
