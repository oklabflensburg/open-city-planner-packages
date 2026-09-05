"""Explicit media negotiation shared by JSON-only and opt-in PostgreSQL applications."""

from fastapi import Request

MEDIA_TYPE = "application/vnd.ocp.registry.v2+json"
SHARED_PATHS = {"/api/v1/search", "/api/v1/publishers", "/api/v1/publishers/{publisher_id}"}


def wants_v2(request: Request) -> bool:
    """Only an explicit acceptable vendor media type opts existing consumers into v2."""
    qualities = {}
    for entry in request.headers.get("accept", "").split(","):
        media, *parameters = entry.strip().lower().split(";")
        quality = 1.0
        for parameter in parameters:
            if parameter.strip().startswith("q="):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0.0
        qualities[media] = quality if 0 <= quality <= 1 else 0.0
    return qualities.get(MEDIA_TYPE, 0) > 0 and qualities[MEDIA_TYPE] >= qualities.get(
        "application/json", 0
    )
