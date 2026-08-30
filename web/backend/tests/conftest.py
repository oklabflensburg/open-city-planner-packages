from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.backend.app.main import app, repository
from web.backend.app.repository import RegistryRepository


@pytest.fixture
def registry_root(tmp_path: Path) -> Path:
    source = json.loads(
        (Path(__file__).parents[3] / "registry/modules/analysis-areas.json").read_text()
    )
    modules = tmp_path / "registry/modules"
    modules.mkdir(parents=True)
    (tmp_path / "registry/registry.json").write_text('{"schema_version": 1}\n')
    fixtures = []
    for module_id, name, publisher_id, publisher_name, classification in (
        ("analysis-areas", "Analysis Areas", "oklabflensburg", "OK Lab Flensburg", "first-party"),
        ("analysis-tools", "Spatial Toolkit", "community", "Community", "reviewed-community"),
        ("energy-map", "Energy Map", "community", "Community", "reviewed-community"),
    ):
        module = copy.deepcopy(source)
        module.update(
            id=module_id,
            name=name,
            publisher={"id": publisher_id, "name": publisher_name},
            classification=classification,
            source_repository=f"https://github.com/oklabflensburg/{module_id}",
        )
        module["description"] = f"Tools for {name.lower()} and municipal planning."
        module["versions"][0]["artifact"]["url"] = (
            f"https://packages.stadtplaner.oklabflensburg.de/modules/{module_id}/"
            f"1.0.0/{module_id}-1.0.0.ocp"
        )
        module["versions"][0]["requires"]["host"] = ">=0.2.0,<1.0.0"
        fixtures.append(module)
    fixtures[1]["versions"][0]["channel"] = "beta"
    fixtures[2]["versions"].append(
        {
            **copy.deepcopy(fixtures[2]["versions"][0]),
            "version": "1.1.0",
            "artifact": {
                "url": "https://packages.stadtplaner.oklabflensburg.de/modules/energy-map/1.1.0/energy-map-1.1.0.ocp",
                "sha256": "b" * 64,
            },
            "source_tag": "v1.1.0",
        }
    )
    for module in fixtures:
        (modules / f"{module['id']}.json").write_text(json.dumps(module))
    return tmp_path / "registry"


@pytest.fixture
def repo(registry_root: Path) -> RegistryRepository:
    return RegistryRepository(registry_root)


@pytest.fixture
def client(repo: RegistryRepository):
    app.dependency_overrides[repository] = lambda: repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
