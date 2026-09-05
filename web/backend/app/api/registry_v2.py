"""Opt-in shadow HTTP adapter; all SQL stays behind the repository/session boundary."""

from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from packaging.version import InvalidVersion, Version
from pydantic import AfterValidator, TypeAdapter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from scripts.registry import RegistryValidationError, canonical_json, validate_semver
from web.backend.app.api.models_registry_v2 import (
    ChannelTarget,
    ModuleDetail,
    ModulePage,
    ModuleSearch,
    PublishedVersion,
    PublisherPage,
    Readiness,
    RegistryError,
    RegistryPublisherDetail,
    VersionPage,
)
from web.backend.app.api.registry_queries import NotFound, RegistryReadService
from web.backend.app.api.representations import MEDIA_TYPE, SHARED_PATHS, wants_v2
from web.backend.app.db.config import database_engine
from web.backend.app.db.repository import RegistryDatabaseRepository
from web.backend.app.models import (
    Channel,
    Classification,
    PublisherDetail,
    PublisherSummary,
    SearchResult,
)

EXPECTED_SCHEMA_REVISION = "0049_promotions"
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def complete_semver(value: str) -> str:
    try:
        return validate_semver(value)
    except RegistryValidationError as exc:
        raise ValueError("Must be a complete SemVer version") from exc


def compatibility_version(value: str) -> str:
    complete_semver(value)
    try:
        Version(value)
    except InvalidVersion as exc:
        raise ValueError("Version cannot be evaluated by the compatibility library") from exc
    return value


SemVer = Annotated[str, AfterValidator(complete_semver)]
CompatibleVersion = Annotated[str, AfterValidator(compatibility_version)]


@contextmanager
def read_repository(engine) -> Iterator[RegistryDatabaseRepository]:
    # Driver transaction options apply before the first statement/snapshot. Session close
    # rolls back; no flush/commit, and connection close returns it to the bounded pool.
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True
        ) as connection,
        Session(bind=connection, autoflush=False, expire_on_commit=False) as session,
    ):
        yield RegistryDatabaseRepository(session)


def db_service(request: Request):
    with read_repository(request.app.state.registry_engine) as repository:
        yield RegistryReadService(repository)


def shared_service(request: Request):
    if wants_v2(request):
        yield from db_service(request)
    else:
        yield None


Service = Annotated[RegistryReadService, Depends(db_service)]
SharedService = Annotated[RegistryReadService | None, Depends(shared_service)]


def metadata(request: Request, value, *, negotiated=False) -> Response:
    body = canonical_json(jsonable_encoder(value)).encode("utf-8")
    etag = '"' + sha256(body).hexdigest() + '"'
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if negotiated:
        headers["Vary"] = "Accept"
    validators = [
        v.strip().removeprefix("W/") for v in request.headers.get("if-none-match", "").split(",")
    ]
    if etag in validators or "*" in validators:
        return Response(status_code=304, headers=headers)
    return Response(
        body, headers=headers, media_type=MEDIA_TYPE if negotiated else "application/json"
    )


def legacy_repository(request):
    from web.backend.app.main import repository

    return request.app.dependency_overrides.get(repository, repository)()


def configure_database(app: FastAPI, *, engine_factory=None):
    @asynccontextmanager
    async def lifespan(application):
        # URL validation and engine creation are mandatory when enabled. Connectivity is
        # checked by readiness/reads, allowing DB-independent liveness during an outage.
        engine = (engine_factory or database_engine)()
        application.state.registry_engine = engine
        try:
            yield
        finally:
            engine.dispose()

    app.router.lifespan_context = lifespan

    @app.exception_handler(SQLAlchemyError)
    async def unavailable(_request, _exc):
        return Response(
            '{"detail":"Registry database unavailable"}',
            status_code=503,
            media_type="application/json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.exception_handler(NotFound)
    async def missing(_request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"detail": str(exc)}, status_code=404, headers={"Cache-Control": "no-cache"}
        )

    @app.get("/ready", response_model=Readiness, tags=["health"])
    def ready(service: Service):
        revision = service.repository.schema_revision()
        if revision != EXPECTED_SCHEMA_REVISION:
            raise HTTPException(503, "Registry database schema is not ready")
        return Readiness(schema_revision=revision)


def configure(app: FastAPI, legacy: APIRouter):
    app.include_router(APIRouter(routes=[r for r in legacy.routes if r.path not in SHARED_PATHS]))
    router = APIRouter(
        tags=["Registry v2 (shadow)"],
        responses={
            404: {"model": RegistryError, "description": "Published record not found"},
            503: {"model": RegistryError, "description": "Registry database unavailable"},
        },
    )

    @app.middleware("http")
    async def cache_boundary(request, call_next):
        response = await call_next(request)
        shared = request.url.path == "/api/v1/search" or request.url.path.startswith(
            "/api/v1/publishers"
        )
        if shared:
            previous = response.headers.get("Vary")
            if not previous or "accept" not in previous.lower().split(", "):
                response.headers["Vary"] = f"{previous}, Accept" if previous else "Accept"
        if (
            request.url.path.startswith("/api/v1/modules")
            or (shared and wants_v2(request))
            or request.url.path == "/ready"
        ):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @router.get("/api/v1/modules", response_model=ModulePage)
    def modules(
        request: Request,
        service: Service,
        limit: Limit = 50,
        offset: Offset = 0,
        publisher: str | None = Query(None, min_length=1, max_length=100),
        classification: Classification | None = None,
        channel: Channel | None = None,
        host: CompatibleVersion | None = None,
        sdk: CompatibleVersion | None = None,
    ):
        """Published modules ordered by name/ID. Channel, host and SDK match one version."""
        return metadata(
            request,
            service.list_modules(
                limit=limit,
                offset=offset,
                publisher=publisher,
                classification=classification,
                channel=channel,
                host=host,
                sdk=sdk,
            ),
        )

    @router.get("/api/v1/modules/{module_id}", response_model=ModuleDetail)
    def module(module_id: str, request: Request, service: Service):
        return metadata(request, service.get_module(module_id))

    @router.get("/api/v1/modules/{module_id}/versions", response_model=VersionPage)
    def versions(
        module_id: str,
        request: Request,
        service: Service,
        limit: Limit = 50,
        offset: Offset = 0,
    ):
        """Immutable history in descending SemVer precedence; exact-string ASC ties."""
        return metadata(request, service.list_versions(module_id, limit=limit, offset=offset))

    @router.get("/api/v1/modules/{module_id}/versions/{version}", response_model=PublishedVersion)
    def version(module_id: str, version: SemVer, request: Request, service: Service):
        return metadata(request, service.get_version(module_id, version))

    @router.get("/api/v1/modules/{module_id}/channels", response_model=dict[Channel, ChannelTarget])
    def channels(module_id: str, request: Request, service: Service):
        """Current explicit pointers, independent of historical publication labels."""
        return metadata(request, service.get_channels(module_id))

    @router.get("/api/v1/search", response_model=SearchResult | ModuleSearch)
    def search(
        request: Request,
        service: SharedService,
        q: str = Query(..., min_length=1, max_length=200),
        limit: Limit = 8,
        offset: Offset = 0,
    ):
        """Explicit v2 Accept header selects ranked DB modules; default retains legacy JSON DTO."""
        if service is None:
            from web.backend.app.main import search as legacy_search

            return legacy_search(legacy_repository(request), q=q, limit=limit, offset=offset)
        if not q.strip():
            raise HTTPException(422, "Search query must not be blank")
        return metadata(
            request, service.list_modules(q=q, limit=limit, offset=offset), negotiated=True
        )

    @router.get("/api/v1/publishers", response_model=list[PublisherSummary] | PublisherPage)
    def publishers(
        request: Request,
        service: SharedService,
        limit: Limit = 50,
        offset: Offset = 0,
    ):
        """Explicit v2 Accept header selects a paginated DB page; default is the legacy list."""
        if service is None:
            return legacy_repository(request).publishers()
        return metadata(
            request, service.list_publishers(limit=limit, offset=offset), negotiated=True
        )

    @router.get(
        "/api/v1/publishers/{publisher_id}",
        response_model=PublisherDetail | RegistryPublisherDetail,
    )
    def publisher(
        publisher_id: str,
        request: Request,
        service: SharedService,
        limit: Limit = 50,
        offset: Offset = 0,
    ):
        """v2 includes a paginated modules page; default retains legacy packages."""
        if service is None:
            from web.backend.app.main import publisher as legacy_publisher

            return legacy_publisher(publisher_id, legacy_repository(request))
        return metadata(
            request,
            service.get_publisher(publisher_id, limit=limit, offset=offset),
            negotiated=True,
        )

    app.include_router(router)
    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        # Each representation has its own documented media type and concrete DTO.
        for path, old, new in (
            ("/api/v1/search", SearchResult, ModuleSearch),
            ("/api/v1/publishers", list[PublisherSummary], PublisherPage),
            ("/api/v1/publishers/{publisher_id}", PublisherDetail, RegistryPublisherDetail),
        ):
            operation = schema["paths"][path]["get"]
            content = operation["responses"]["200"]["content"]
            for media_type, model in (("application/json", old), (MEDIA_TYPE, new)):
                definition = TypeAdapter(model).json_schema(
                    ref_template="#/components/schemas/{model}"
                )
                definition.pop("$defs", None)
                content[media_type] = {"schema": definition}
            if not any(p["name"] == "Accept" for p in operation.get("parameters", [])):
                operation.setdefault("parameters", []).append(
                    {
                        "name": "Accept",
                        "in": "header",
                        "required": False,
                        "description": f"Use {MEDIA_TYPE} for the DB-backed v2 contract.",
                        "schema": {"type": "string", "default": "application/json"},
                    }
                )
        for path, operations in schema["paths"].items():
            if path.startswith("/api/v1/modules") or path in SHARED_PATHS:
                operations["get"]["responses"]["304"] = {"description": "Representation unchanged"}
        return schema

    app.openapi = openapi
