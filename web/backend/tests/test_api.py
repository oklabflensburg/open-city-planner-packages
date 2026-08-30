from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from web.backend.app.models import Publisher
from web.backend.app.repository import PackageQuery, RegistryRepository


def test_registry_loads_validated_modules_read_only(repo: RegistryRepository) -> None:
    assert repo.package_count == 3
    assert repo.package("analysis-areas").latest_version == "1.0.0"
    assert repo.package("energy-map").latest_version == "1.1.0"


def test_search_ranking_is_deterministic(repo: RegistryRepository) -> None:
    exact_id = repo.list_packages(PackageQuery(q="analysis-areas"))
    exact_name = repo.list_packages(PackageQuery(q="Spatial Toolkit"))
    prefix = repo.list_packages(PackageQuery(q="analysis"))
    publisher = repo.list_packages(PackageQuery(q="Community"))
    assert [item.id for item in exact_id] == ["analysis-areas"]
    assert [item.id for item in exact_name] == ["analysis-tools"]
    assert [item.id for item in prefix] == ["analysis-areas", "analysis-tools"]
    assert [item.id for item in publisher] == ["analysis-tools", "energy-map"]


def test_filters_and_compatibility(repo: RegistryRepository) -> None:
    assert [item.id for item in repo.list_packages(PackageQuery(publisher="community"))] == [
        "analysis-tools",
        "energy-map",
    ]
    assert [item.id for item in repo.list_packages(PackageQuery(channel="beta"))] == [
        "analysis-tools"
    ]
    assert len(repo.list_packages(PackageQuery(host="0.2.5"))) == 3
    assert repo.list_packages(PackageQuery(host="1.2.0")) == []


def test_packages_api_paginates_and_validates_limits(client: TestClient) -> None:
    response = client.get("/api/v1/packages", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert len(response.json()["items"]) == 1
    assert client.get("/api/v1/packages", params={"limit": 101}).status_code == 422
    assert client.get("/api/v1/packages", params={"offset": -1}).status_code == 422


def test_search_api_uses_ranked_bounded_results(client: TestClient) -> None:
    response = client.get("/api/v1/search", params={"q": "analysis", "limit": 1})
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["items"][0]["id"] == "analysis-areas"
    assert client.get("/api/v1/search", params={"q": ""}).status_code == 422


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("/api/v1/packages/missing", "Package not found"),
        ("/api/v1/packages/analysis-areas/versions/9.9.9", "Version not found"),
        ("/api/v1/publishers/missing", "Publisher not found"),
    ],
)
def test_not_found_contracts(client: TestClient, path: str, detail: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert response.json() == {"detail": detail}


def test_package_and_version_contracts_use_registry_artifact_url(client: TestClient) -> None:
    package = client.get("/api/v1/packages/analysis-areas").json()
    version = client.get("/api/v1/packages/analysis-areas/versions/1.0.0").json()
    assert package["versions"][0] == version
    assert version["artifact"]["url"].endswith("analysis-areas-1.0.0.ocp")
    assert version["artifact"]["sha256"] == (
        "7006f31ea73f40e38f63d2065652c27ad5d3391ddcc8cfad2f149993efef3dcf"
    )


def test_publisher_aggregation_contains_no_invented_downloads(client: TestClient) -> None:
    publishers = client.get("/api/v1/publishers").json()
    community = next(item for item in publishers if item["id"] == "community")
    assert community["package_count"] == 2
    assert community["release_count"] == 3
    assert "downloads" not in community
    detail = client.get("/api/v1/publishers/community").json()
    assert [item["id"] for item in detail["packages"]] == ["analysis-tools", "energy-map"]


def test_health_reports_loaded_registry(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {
        "status": "ok",
        "registry_schema": 1,
        "packages": 3,
    }


def test_pydantic_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Publisher(id="oklabflensburg", name="OK Lab Flensburg", downloads=10)
