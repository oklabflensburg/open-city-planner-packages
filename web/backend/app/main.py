"""FastAPI application for read-only Open City Planner package discovery."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from web.backend.app.api.representations import wants_v2
from web.backend.app.models import (
    HealthResponse,
    PackageDetail,
    PackagePage,
    PackageRelease,
    PublisherDetail,
    PublisherSummary,
    SearchResult,
)
from web.backend.app.repository import PackageQuery, RegistryRepository

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@lru_cache
def repository() -> RegistryRepository:
    root = Path(os.environ.get("PACKAGES_REGISTRY_SOURCE", REPOSITORY_ROOT / "registry"))
    return RegistryRepository(root)


Repository = Annotated[RegistryRepository, Depends(repository)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]

router = APIRouter()


def page(items: list, limit: int, offset: int) -> tuple[list, int]:
    return items[offset : offset + limit], len(items)


@router.get("/api/v1/health", response_model=HealthResponse)
def health(repo: Repository) -> HealthResponse:
    return HealthResponse(packages=repo.package_count)


@router.get("/api/v1/packages", response_model=PackagePage)
def packages(
    repo: Repository,
    q: str = Query("", max_length=200),
    publisher: str | None = Query(None, max_length=100),
    classification: Literal["first-party", "reviewed-community"] | None = None,
    channel: Literal["stable", "beta", "nightly"] | None = None,
    host: str | None = Query(None, max_length=50),
    sdk: str | None = Query(None, max_length=50),
    sort: Literal["relevance", "name", "id", "version"] = "relevance",
    limit: Limit = 24,
    offset: Offset = 0,
) -> PackagePage:
    matches = repo.list_packages(
        PackageQuery(q, publisher, classification, channel, host, sdk, sort)
    )
    items, total = page(matches, limit, offset)
    return PackagePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/api/v1/search", response_model=SearchResult)
def search(
    repo: Repository,
    q: str = Query(..., min_length=1, max_length=200),
    limit: Limit = 8,
    offset: Offset = 0,
) -> SearchResult:
    matches = repo.list_packages(PackageQuery(q=q))
    items, total = page(matches, limit, offset)
    return SearchResult(items=items, total=total, limit=limit, offset=offset, query=q)


@router.get("/api/v1/packages/{module_id}", response_model=PackageDetail)
def package(module_id: str, repo: Repository) -> PackageDetail:
    result = repo.package(module_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Package not found")
    return result


@router.get("/api/v1/packages/{module_id}/versions", response_model=list[PackageRelease])
def versions(module_id: str, repo: Repository) -> list[PackageRelease]:
    result = repo.versions(module_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Package not found")
    return result


@router.get("/api/v1/packages/{module_id}/versions/{version}", response_model=PackageRelease)
def version(module_id: str, version: str, repo: Repository) -> PackageRelease:
    if repo.package(module_id) is None:
        raise HTTPException(status_code=404, detail="Package not found")
    result = repo.version(module_id, version)
    if result is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return result


@router.get("/api/v1/publishers", response_model=list[PublisherSummary])
def publishers(repo: Repository) -> list[PublisherSummary]:
    return repo.publishers()


@router.get("/api/v1/publishers/{publisher_id}", response_model=PublisherDetail)
def publisher(publisher_id: str, repo: Repository) -> PublisherDetail:
    result = repo.publisher(publisher_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    return result


def create_app(
    *, v2_enabled: bool | None = None, v1_compat_enabled: bool | None = None, engine_factory=None
) -> FastAPI:
    """Keep the production JSON app independent of optional PostgreSQL dependencies."""
    if v2_enabled is None:
        value = os.environ.get("PACKAGES_REGISTRY_V2_API_ENABLED", "false").lower()
        if value not in {"true", "false"}:
            raise ValueError("PACKAGES_REGISTRY_V2_API_ENABLED must be true or false")
        v2_enabled = value == "true"
    if v1_compat_enabled is None:
        value = os.environ.get("PACKAGES_REGISTRY_V1_DB_COMPAT_ENABLED", "false").lower()
        if value not in {"true", "false"}:
            raise ValueError("PACKAGES_REGISTRY_V1_DB_COMPAT_ENABLED must be true or false")
        v1_compat_enabled = value == "true"
    application = FastAPI(
        title="Open City Planner Packages API",
        version="1.0.0",
        description="Read-only Registry discovery. JSON remains production authority; "
        "explicitly enabled Registry v2 representations read a shadow PostgreSQL database.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET"],
        allow_headers=["*"],
        expose_headers=["ETag"],
    )
    if v2_enabled or v1_compat_enabled:
        from web.backend.app.api.registry_v2 import configure_database

        configure_database(application, engine_factory=engine_factory)
    if v1_compat_enabled:
        from web.backend.app.api.registry_v1 import configure_compatibility

        configure_compatibility(application)
    if v2_enabled:
        from web.backend.app.api.registry_v2 import configure

        configure(application, router)
    else:
        application.include_router(router)

        @application.middleware("http")
        async def disabled_representation(request, call_next):
            shared = request.url.path == "/api/v1/search" or request.url.path.startswith(
                "/api/v1/publishers"
            )
            if shared and wants_v2(request):
                return JSONResponse(
                    {"detail": "Registry v2 representation is not enabled"},
                    status_code=406,
                    headers={"Vary": "Accept", "Cache-Control": "no-cache"},
                )
            response = await call_next(request)
            if shared:
                previous = response.headers.get("Vary")
                response.headers["Vary"] = f"{previous}, Accept" if previous else "Accept"
            return response

    from web.backend.app.api.models_registry_v2 import Liveness

    @application.get("/health", response_model=Liveness, tags=["health"])
    def liveness() -> Liveness:
        return Liveness()

    return application


app = create_app()
