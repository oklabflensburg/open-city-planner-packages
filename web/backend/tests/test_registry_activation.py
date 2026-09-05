"""Production app startup must remain independent of optional database packages/config."""

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from web.backend.app.api.representations import MEDIA_TYPE
from web.backend.app.main import create_app


def test_json_only_startup_without_database_dependencies():
    code = """
import importlib.abc
import sys
class NoDatabase(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".")[0] in {"sqlalchemy", "psycopg", "alembic"}:
            raise AssertionError("Optional database dependency imported: " + fullname)
sys.meta_path.insert(0, NoDatabase())
from fastapi.testclient import TestClient
from web.backend.app.main import app
with TestClient(app) as client:
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/packages").status_code == 200
    assert client.get("/api/v1/modules").status_code == 404
    assert client.get("/ready").status_code == 404
    assert "/api/v1/modules" not in client.get("/openapi.json").json()["paths"]
"""
    env = {
        **os.environ,
        "PACKAGES_REGISTRY_V2_API_ENABLED": "false",
        "PACKAGES_REGISTRY_DATABASE_URL": "invalid-and-unused",
    }
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_disabled_v2_representation_is_not_silently_served_as_legacy():
    with TestClient(create_app(v2_enabled=False)) as client:
        response = client.get("/api/v1/publishers", headers={"Accept": MEDIA_TYPE})
        assert response.status_code == 406
        assert response.headers["Vary"] == "Accept"
        assert client.get("/api/v1/publishers").status_code == 200


def test_invalid_activation_flag_fails_explicitly(monkeypatch):
    monkeypatch.setenv("PACKAGES_REGISTRY_V2_API_ENABLED", "typo")
    with pytest.raises(ValueError, match="must be true or false"):
        create_app()
