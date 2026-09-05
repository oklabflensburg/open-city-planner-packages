"""Registry v2 HTTP contracts against migrated, imported, disposable PostgreSQL schemas."""

import copy
import json

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import event, insert, select, text, update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from scripts.registry import load_registry
from web.backend.app.api.registry_v2 import (
    EXPECTED_SCHEMA_REVISION,
    MEDIA_TYPE,
    read_repository,
)
from web.backend.app.db.models import (
    Artifact,
    BuildProvenance,
    Module,
    ModuleChannel,
    Publisher,
)
from web.backend.app.db.repository import RegistryDatabaseRepository
from web.backend.app.main import create_app
from web.backend.app.registry_import_v1 import import_registry
from web.backend.db_tests.conftest import ROOT, migration_config

V2 = {"Accept": MEDIA_TYPE}
SOURCE = ROOT / "registry"


@pytest.fixture
def api_engine(pg_engine):
    import_registry(pg_engine, SOURCE)
    return pg_engine


@pytest.fixture
def client(api_engine):
    with TestClient(create_app(v2_enabled=True, engine_factory=lambda: api_engine)) as client:
        yield client


def add_version(engine, module_id, version, *, host=None, sdk=None):
    module = next(m for m in load_registry(SOURCE) if m["id"] == module_id)
    release = copy.deepcopy(module["versions"][-1])
    release["artifact"]["url"] = (
        f"https://packages.stadtplaner.oklabflensburg.de/modules/{module_id}/{version}/"
        f"{module_id}-{version}.ocp"
    )
    release["version"] = version
    release["source_tag"] = "v" + version
    if "-" in version.split("+")[0]:
        release["channel"] = "beta"
    if host is not None:
        release["requires"]["host"] = host
    if sdk is not None:
        release["requires"]["sdk"] = sdk
    with Session(engine) as session, session.begin():
        RegistryDatabaseRepository(session).insert_published_version(module_id, release)


def test_modules_and_current_channels(client):
    response = client.get("/api/v1/modules")
    assert response.status_code == 200
    page = response.json()
    assert (page["total"], page["limit"], page["offset"]) == (3, 50, 0)
    assert [(m["name"], m["id"]) for m in page["items"]] == sorted(
        (m["name"], m["id"]) for m in page["items"]
    )
    assert sum(m["version_count"] for m in page["items"]) == 6
    items = {m["id"]: m for m in page["items"]}
    assert items["analysis-areas"]["stable_version"] == "1.5.3"
    assert items["statistics"]["stable_version"] == "0.3.0"
    assert items["search"]["stable_version"] is None
    assert items["search"]["channels"]["beta"]["version"] == "0.1.0"
    assert set(items["statistics"]) == {
        "id",
        "name",
        "description",
        "publisher",
        "classification",
        "license",
        "source_repository",
        "homepage",
        "documentation_url",
        "stable_version",
        "channels",
        "version_count",
    }
    detail = client.get("/api/v1/modules/statistics").json()
    assert detail == {**items["statistics"], "versions_url": "/api/v1/modules/statistics/versions"}
    assert client.get("/api/v1/modules/search/channels").json() == items["search"]["channels"]


def test_version_contract_preserves_every_historical_field(client):
    for module in load_registry(SOURCE):
        for release in module["versions"]:
            response = client.get(f"/api/v1/modules/{module['id']}/versions/{release['version']}")
            assert response.status_code == 200
            value = response.json()
            assert value == {
                "module_id": module["id"],
                "version": release["version"],
                "historical_publication_channel": release["channel"],
                "bundle_format_version": release["bundle_format_version"],
                "artifact": {**release["artifact"], "byte_size": None, "storage_locator": None},
                "source": {
                    "repository": module["source_repository"],
                    "tag": release.get("source_tag"),
                    "commit": release["source_commit"],
                },
                "compatibility": {k: release["requires"][k] for k in ("host", "sdk")},
                "dependencies": release["requires"]["modules"],
                "published_at": None,
                "provenance": {
                    k: None
                    for k in (
                        "builder_version",
                        "builder_commit",
                        "host_commit",
                        "reproducible",
                        "host_contract_status",
                        "environment",
                    )
                },
            }


def test_versions_semver_pagination_and_build_metadata_ties(client, api_engine):
    for version in ("1.9.0", "1.10.0+b", "1.10.0+a", "1.10.0-rc.2", "1.10.0-rc.10"):
        add_version(api_engine, "statistics", version)
    page = client.get("/api/v1/modules/statistics/versions", params={"limit": 4}).json()
    assert page["total"] == 7
    assert [v["version"] for v in page["items"]] == [
        "1.10.0+a",
        "1.10.0+b",
        "1.10.0-rc.10",
        "1.10.0-rc.2",
    ]
    next_page = client.get("/api/v1/modules/statistics/versions", params={"offset": 4}).json()
    assert [v["version"] for v in next_page["items"]] == ["1.9.0", "0.3.0", "0.2.0"]
    assert client.get("/api/v1/modules/statistics").json()["stable_version"] == "0.3.0"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/modules",
        "/api/v1/modules/analysis-areas/versions",
        "/api/v1/publishers",
        "/api/v1/search?q=OK",
        "/api/v1/publishers/oklabflensburg",
    ],
)
def test_pagination_boundaries(client, path):
    first = client.get(path, params={"q": "OK", "limit": 1, "offset": 0}, headers=V2).json()
    first = first.get("modules", first)
    assert len(first["items"]) == 1
    params = {"limit": 100, "offset": 100, "q": "OK"}
    last = client.get(path, params=params, headers=V2).json()
    last = last.get("modules", last)
    assert last == {**last, "items": [], "offset": 100, "limit": 100, "total": first["total"]}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/modules",
        "/api/v1/modules/statistics/versions",
        "/api/v1/publishers",
        "/api/v1/search",
        "/api/v1/publishers/oklabflensburg",
    ],
)
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_invalid_pagination(client, path, params):
    response = client.get(path, params={"q": "OK", **params}, headers=V2)
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize(
    "params",
    [
        {"classification": "trusted"},
        {"channel": "latest"},
        {"host": "1.2"},
        {"sdk": "garbage"},
        {"host": ">=1.2.0"},
        {"publisher": ""},
    ],
)
def test_invalid_filters(client, params):
    assert client.get("/api/v1/modules", params=params).status_code == 422


@pytest.mark.parametrize(
    "path,detail",
    [
        ("/api/v1/modules/nope", "Module not found"),
        ("/api/v1/modules/nope/versions", "Module not found"),
        ("/api/v1/modules/nope/channels", "Module not found"),
        ("/api/v1/modules/nope/versions/1.0.0", "Module not found"),
        ("/api/v1/modules/statistics/versions/9.9.9", "Version not found"),
        ("/api/v1/publishers/nope", "Publisher not found"),
    ],
)
def test_missing_records(client, path, detail):
    response = client.get(path, headers=V2)
    assert response.status_code == 404
    assert response.json() == {"detail": detail}
    assert response.headers["Cache-Control"] == "no-cache"


def test_invalid_exact_semver_and_search(client):
    assert client.get("/api/v1/modules/statistics/versions/latest").status_code == 422
    for q in ("", " ", "x" * 201):
        assert client.get("/api/v1/search", params={"q": q}, headers=V2).status_code == 422


def test_same_version_filters_and_current_not_historical_channel(client, api_engine):
    add_version(api_engine, "statistics", "0.5.0", host=">=5.0.0,<6.0.0", sdk=">=1.0.0,<2.0.0")
    add_version(api_engine, "statistics", "0.6.0", host=">=6.0.0,<7.0.0", sdk=">=2.0.0,<3.0.0")

    def matching(**params):
        return client.get(
            "/api/v1/modules", params={"publisher": "oklabflensburg", **params}
        ).json()

    assert matching(host="5.1.0", sdk="2.1.0")["items"] == []
    assert matching(channel="stable", host="5.1.0")["items"] == []
    assert [m["id"] for m in matching(host="5.1.0", sdk="1.1.0")["items"]] == ["statistics"]
    with api_engine.begin() as connection:
        connection.execute(
            update(ModuleChannel)
            .where(ModuleChannel.module_id == "statistics", ModuleChannel.channel == "stable")
            .values(version="0.5.0", revision=2)
        )
    assert [m["id"] for m in matching(channel="stable", host="5.1.0", sdk="1.1.0")["items"]] == [
        "statistics"
    ]
    assert matching(channel="stable", host="6.1.0", sdk="2.1.0")["items"] == []
    assert matching(classification="reviewed-community")["total"] == 0
    assert matching(publisher="missing")["total"] == 0
    historical = client.get("/api/v1/modules/statistics/versions/0.3.0").json()
    assert historical["historical_publication_channel"] == "stable"


def test_search_all_ranking_tiers_ties_and_literal_wildcards(client, api_engine):
    # Create actual published versions through the importer rather than candidate metadata.
    module = load_registry(SOURCE)[-1]
    with Session(api_engine) as session, session.begin():
        repo = RegistryDatabaseRepository(session)
        for module_id, name, description in (
            ("needle", "Other", "none"),
            ("exact-name", "Needle", "none"),
            ("needle-prefix", "Other", "none"),
            ("a-contains-needle", "Other", "none"),
            ("description-hit", "Other", "Needle"),
        ):
            source = {
                k: v
                for k, v in module.items()
                if k not in ("publisher", "versions", "schema_version")
            }
            source.update(
                id=module_id, name=name, description=description, publisher_id="oklabflensburg"
            )
            session.add(Module(**source))
            session.flush()
            repo.insert_published_version(module_id, copy.deepcopy(module["versions"][0]))
    response = client.get("/api/v1/search", params={"q": "NEEDLE"}, headers=V2).json()
    assert [m["id"] for m in response["items"]] == [
        "needle",
        "exact-name",
        "needle-prefix",
        "a-contains-needle",
        "description-hit",
    ]
    publisher = client.get("/api/v1/search", params={"q": "OK Lab"}, headers=V2).json()
    assert publisher["total"] == 8
    assert [m["id"] for m in publisher["items"]] == sorted(m["id"] for m in publisher["items"])
    for query in ("%", "_", "' OR 1=1 --"):
        assert client.get("/api/v1/search", params={"q": query}, headers=V2).json()["total"] == 0


def test_publishers_and_candidate_only_exclusion(client, api_engine):
    with api_engine.begin() as connection:
        connection.execute(insert(Publisher).values(id="candidate-publisher", name="Candidate"))
        connection.execute(
            insert(Module).values(
                id="candidate-only",
                name="Candidate",
                publisher_id="candidate-publisher",
                classification="first-party",
                license="MIT",
                source_repository="https://example.org/code",
            )
        )
        connection.execute(
            insert(BuildProvenance).values(
                source_repository="https://example.org/code",
                source_commit="a" * 40,
                builder_version="candidate-secret",
                reproducible=True,
            )
        )
    page = client.get("/api/v1/publishers", headers=V2).json()
    assert page["items"] == [
        {"id": "oklabflensburg", "name": "OK Lab Flensburg", "module_count": 3}
    ]
    detail = client.get("/api/v1/publishers/oklabflensburg", headers=V2).json()
    assert detail["module_count"] == detail["modules"]["total"] == 3
    assert client.get("/api/v1/modules/candidate-only").status_code == 404
    assert client.get("/api/v1/publishers/candidate-publisher", headers=V2).status_code == 404
    assert client.get("/api/v1/search?q=candidate", headers=V2).json()["total"] == 0
    assert client.get("/api/v1/modules/statistics/versions/0.4.0").status_code == 404


def test_etag_revalidation_and_representation_mutations(client, api_engine):
    path = "/api/v1/modules/statistics"
    first = client.get(path)
    etag = first.headers["ETag"]
    assert first.headers["Cache-Control"] == "no-cache"
    assert client.get(path).headers["ETag"] == etag
    for validator in (etag, "W/" + etag, '"different", ' + etag, "*"):
        response = client.get(path, headers={"If-None-Match": validator})
        assert response.status_code == 304
        assert response.content == b""
        assert response.headers["ETag"] == etag
    with api_engine.begin() as connection:
        connection.execute(
            update(ModuleChannel)
            .where(ModuleChannel.module_id == "statistics")
            .values(version="0.2.0", revision=2)
        )
    changed = client.get(path, headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.json()["stable_version"] == "0.2.0"
    assert changed.headers["ETag"] != etag
    version_path = path + "/versions/0.3.0"
    version = client.get(version_path)
    with api_engine.begin() as connection:
        connection.execute(
            update(Artifact)
            .where(Artifact.digest == version.json()["artifact"]["sha256"])
            .values(byte_size=123, storage_locator="sha256/example")
        )
    enriched = client.get(version_path, headers={"If-None-Match": version.headers["ETag"]})
    assert enriched.status_code == 200
    assert enriched.json()["artifact"]["url"] == version.json()["artifact"]["url"]
    assert enriched.json()["artifact"]["byte_size"] == 123


def test_response_uses_one_snapshot_and_next_request_sees_commits(client, api_engine):
    changed = False

    def concurrent_commit(conn, cursor, statement, parameters, context, executemany):
        nonlocal changed
        if not changed and statement.startswith("SELECT modules."):
            changed = True
            with api_engine.begin() as other:
                other.execute(
                    update(Module).where(Module.id == "statistics").values(name="Changed")
                )
                other.execute(
                    update(ModuleChannel)
                    .where(ModuleChannel.module_id == "statistics")
                    .values(version="0.2.0", revision=2)
                )

    event.listen(api_engine, "after_cursor_execute", concurrent_commit)
    try:
        first = client.get("/api/v1/modules/statistics").json()
    finally:
        event.remove(api_engine, "after_cursor_execute", concurrent_commit)
    assert changed
    assert first["name"] != "Changed"
    assert first["stable_version"] == "0.3.0"
    second = client.get("/api/v1/modules/statistics").json()
    assert second["name"] == "Changed"
    assert second["stable_version"] == "0.2.0"
    assert api_engine.pool.checkedout() == 0


def test_transactions_are_read_only_and_connections_reset(api_engine):
    with read_repository(api_engine) as repo:
        assert repo.session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert repo.session.scalar(text("SHOW transaction_read_only")) == "on"
        with pytest.raises(DBAPIError):
            repo.session.execute(text("UPDATE publishers SET name = 'forbidden'"))
    assert api_engine.pool.checkedout() == 0
    with api_engine.connect() as connection:
        assert connection.scalar(text("SHOW transaction_read_only")) == "off"
        assert connection.scalar(select(Publisher.name)) == "OK Lab Flensburg"


def test_batched_query_count_does_not_grow_with_result_size(client, api_engine):
    queries = []

    def record(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(api_engine, "before_cursor_execute", record)
    try:
        for limit in (1, 100):
            queries.clear()
            assert client.get("/api/v1/modules", params={"limit": limit}).status_code == 200
            assert len(queries) == 3
            assert all(q.startswith("SELECT") for q in queries)
        queries.clear()
        assert client.get("/api/v1/modules/analysis-areas/versions").status_code == 200
        assert len(queries) == 3
    finally:
        event.remove(api_engine, "before_cursor_execute", record)


def test_db_outage_is_sanitized_and_never_falls_back(client, api_engine):
    def fail(*args, **kwargs):
        raise OperationalError("private statement", {}, Exception("secret-user:secret-pass@host"))

    event.listen(api_engine, "before_cursor_execute", fail)
    try:
        for path in ("/api/v1/modules", "/api/v1/publishers", "/api/v1/search?q=OK", "/ready"):
            response = client.get(path, headers=V2)
            assert response.status_code == 503
            assert response.json() == {"detail": "Registry database unavailable"}
            assert "secret" not in response.text
            assert response.headers["Cache-Control"] == "no-cache"
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/packages").status_code == 200
        assert client.get("/api/v1/publishers").status_code == 200
    finally:
        event.remove(api_engine, "before_cursor_execute", fail)
    assert api_engine.pool.checkedout() == 0
    assert client.get("/ready").status_code == 200


def test_health_readiness_and_revision_guard(client, api_engine):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health").json()["registry_schema"] == 1
    assert client.get("/ready").json() == {
        "status": "ok",
        "source": "postgresql",
        "schema_revision": EXPECTED_SCHEMA_REVISION,
    }
    assert ScriptDirectory.from_config(migration_config(None)).get_current_head() == (
        EXPECTED_SCHEMA_REVISION
    )
    with api_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'unknown'"))
    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200


def test_enabled_app_preserves_legacy_contracts_and_content_negotiation(client):
    with TestClient(create_app(v2_enabled=False)) as legacy:
        for path in (
            "/api/v1/packages",
            "/api/v1/packages/statistics",
            "/api/v1/packages/statistics/versions",
            "/api/v1/packages/statistics/versions/0.3.0",
            "/api/v1/publishers",
            "/api/v1/publishers/oklabflensburg",
            "/api/v1/search?q=statistics",
            "/api/v1/health",
        ):
            assert client.get(path).json() == legacy.get(path).json()
    for accept in (
        "*/*",
        "application/json",
        MEDIA_TYPE + ";q=0",
        MEDIA_TYPE + ";q=0.5, application/json",
    ):
        assert isinstance(client.get("/api/v1/publishers", headers={"Accept": accept}).json(), list)
    result = client.get("/api/v1/publishers", headers=V2)
    assert result.headers["Content-Type"] == MEDIA_TYPE
    assert "Accept" in result.headers["Vary"]
    assert isinstance(result.json(), dict)
    conditional = client.get(
        "/api/v1/publishers", headers={**V2, "If-None-Match": result.headers["ETag"]}
    )
    assert conditional.status_code == 304
    assert "Accept" in conditional.headers["Vary"]


def test_db_representations_do_not_load_json(client, monkeypatch):
    from web.backend.app import main

    def fail():
        raise AssertionError("JSON source accessed by a DB representation")

    monkeypatch.setattr(main, "repository", fail)
    for path in ("/api/v1/modules", "/api/v1/search?q=OK", "/api/v1/publishers"):
        assert client.get(path, headers=V2).status_code == 200


def test_openapi_schemas_validate_actual_responses_and_no_write_routes(client):
    schema = client.get("/openapi.json").json()
    examples = {
        "/api/v1/modules": "/api/v1/modules",
        "/api/v1/modules/{module_id}": "/api/v1/modules/statistics",
        "/api/v1/modules/{module_id}/versions": "/api/v1/modules/statistics/versions",
        "/api/v1/modules/{module_id}/versions/{version}": (
            "/api/v1/modules/statistics/versions/0.3.0"
        ),
        "/api/v1/modules/{module_id}/channels": "/api/v1/modules/statistics/channels",
        "/api/v1/publishers": "/api/v1/publishers",
        "/api/v1/publishers/{publisher_id}": "/api/v1/publishers/oklabflensburg",
        "/api/v1/search": "/api/v1/search?q=OK",
    }
    for template, path in examples.items():
        operation = schema["paths"][template]["get"]
        for media_type, definition in operation["responses"]["200"]["content"].items():
            response = client.get(path, headers={"Accept": media_type})
            contract = {**definition["schema"], "components": schema["components"]}
            Draft202012Validator.check_schema(contract)
            Draft202012Validator(contract).validate(response.json())
        for method in ("post", "put", "patch", "delete"):
            assert method not in schema["paths"][template]
            assert getattr(client, method)(path).status_code == 405
    serialized = json.dumps(schema)
    assert "historical_publication_channel" in serialized
    assert "null never means false" in serialized


def test_enabled_startup_requires_configuration_and_owns_engine_lifecycle(monkeypatch, pg_engine):
    monkeypatch.delenv("PACKAGES_REGISTRY_DATABASE_URL", raising=False)
    with (
        pytest.raises(ValueError, match="PACKAGES_REGISTRY_DATABASE_URL is required"),
        TestClient(create_app(v2_enabled=True)),
    ):
        pass
    disposed = []
    event.listen(pg_engine, "engine_disposed", lambda engine: disposed.append(engine))
    with TestClient(create_app(v2_enabled=True, engine_factory=lambda: pg_engine)) as client:
        assert client.get("/health").status_code == 200
        assert disposed == []
    assert disposed == [pg_engine]


def test_connection_refusal_returns_503_while_liveness_stays_up(pg_engine):
    from sqlalchemy import create_engine

    # A real refused connection, in addition to statement-level outage coverage above.
    unavailable = create_engine(
        pg_engine.url.set(port=1), connect_args={"connect_timeout": 1}, hide_parameters=True
    )
    with TestClient(create_app(v2_enabled=True, engine_factory=lambda: unavailable)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        for path in ("/ready", "/api/v1/modules", "/api/v1/publishers"):
            response = client.get(path, headers=V2)
            assert response.status_code == 503
            assert response.json() == {"detail": "Registry database unavailable"}
        assert client.get("/api/v1/packages").status_code == 200


def test_present_provenance_is_projected_without_changing_source_binding(client, api_engine):
    from web.backend.app.db.models import ModuleVersion

    path = "/api/v1/modules/statistics/versions/0.3.0"
    original = client.get(path)
    evidence = {
        "builder_version": "1.0.0",
        "builder_commit": "b" * 40,
        "host_commit": "c" * 40,
        "reproducible": False,
        "host_contract_status": "failed",
        "environment_json": {"python": "3.13", "checks": ["build", "host"]},
    }
    # Fixture setup through privileged SQL models an already-published v2 record;
    # HTTP remains read-only and has no evidence-editing interface.
    with api_engine.begin() as connection:
        evidence_id = connection.scalar(
            insert(BuildProvenance)
            .values(
                source_repository=original.json()["source"]["repository"],
                source_commit=original.json()["source"]["commit"],
                **evidence,
            )
            .returning(BuildProvenance.id)
        )
        connection.execute(
            update(ModuleVersion)
            .where(ModuleVersion.module_id == "statistics", ModuleVersion.version == "0.3.0")
            .values(build_provenance_id=evidence_id)
        )
    response = client.get(path, headers={"If-None-Match": original.headers["ETag"]})
    assert response.status_code == 200
    assert response.json()["source"] == original.json()["source"]
    assert response.json()["provenance"] == {
        **{k: v for k, v in evidence.items() if k != "environment_json"},
        "environment": evidence["environment_json"],
    }
