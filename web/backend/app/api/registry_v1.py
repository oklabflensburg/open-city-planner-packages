"""Opt-in v1 metadata routes. No file source, fallback, cache or mutation path."""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from scripts.registry import RegistryValidationError, validate_module_id
from web.backend.app.api.registry_compatibility import (
    RegistryCompatibilityService,
    V1RepresentabilityError,
)
from web.backend.app.api.registry_v2 import EXPECTED_SCHEMA_REVISION, metadata, read_repository


def compatibility_service(request: Request):
    with read_repository(request.app.state.registry_engine) as repository:
        if repository.schema_revision() != EXPECTED_SCHEMA_REVISION:
            raise HTTPException(503, "Registry database schema is not ready")
        yield RegistryCompatibilityService(repository)


Service = Annotated[RegistryCompatibilityService, Depends(compatibility_service)]


def configure_compatibility(app: FastAPI):
    @app.exception_handler(V1RepresentabilityError)
    @app.exception_handler(RegistryValidationError)
    async def invalid_projection(_request, _exc):
        return JSONResponse(
            {"detail": "Registry v1 compatibility verification failed"},
            status_code=503,
            headers={"Cache-Control": "no-cache"},
        )

    @app.middleware("http")
    async def cache_boundary(request, call_next):
        response = await call_next(request)
        if request.url.path in {"/index.json", "/ready"} or (
            request.url.path.startswith("/modules/") and request.url.path.endswith(".json")
        ):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/index.json", tags=["Registry v1 compatibility"])
    def index(request: Request, service: Service):
        return metadata(request, service.index())

    @app.get("/modules/{module_id}.json", tags=["Registry v1 compatibility"])
    def module(module_id: str, request: Request, service: Service):
        try:
            validate_module_id(module_id)
        except RegistryValidationError:
            raise HTTPException(404, "Published module not found") from None
        return metadata(request, service.module(module_id))
