"""Registry API switches and the regular deployment's promotion runtime contract."""

from itertools import product
from pathlib import Path

import jinja2
import pytest
import yaml

ROLE = Path(__file__).resolve().parents[1] / "roles/packages_registry"
ROOT = ROLE.parents[3]
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
TEMPLATE = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
    (ROLE / "templates/packages-registry-backend.service.j2").read_text()
)


@pytest.mark.parametrize("v2,compat", product([False, True, "false", "true"], repeat=2))
def test_api_activation_is_normalized_and_independent(v2, compat):
    def enabled(value):
        return str(value).lower() == "true"

    rendered = TEMPLATE.render(
        {
            **DEFAULTS,
            "packages_registry_v2_api_enabled": v2,
            "packages_registry_v1_db_compat_enabled": compat,
        }
    )
    lines = rendered.splitlines()
    assert ("Environment=PACKAGES_REGISTRY_V2_API_ENABLED=true" in lines) == enabled(v2)
    assert ("Environment=PACKAGES_REGISTRY_V1_DB_COMPAT_ENABLED=true" in lines) == enabled(
        compat
    )
    assert ("EnvironmentFile=" in rendered) == (enabled(v2) or enabled(compat))
    if not enabled(v2):
        assert "UnsetEnvironment=PACKAGES_REGISTRY_V2_API_ENABLED" in lines
    if not enabled(compat):
        assert "UnsetEnvironment=PACKAGES_REGISTRY_V1_DB_COMPAT_ENABLED" in lines


def test_v2_defaults_off_and_does_not_enable_legacy_routing():
    assert DEFAULTS["packages_registry_v2_api_enabled"] is False
    assert DEFAULTS["packages_registry_v1_db_compat_enabled"] is False
    assert DEFAULTS["packages_registry_v1_db_compat_routing_enabled"] is False
    nginx = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
        (ROLE / "templates/packages-registry.nginx.conf.j2").read_text()
    )
    rendered = nginx.render({**DEFAULTS, "packages_registry_v2_api_enabled": True})
    index = rendered.split("location = /index.json {", 1)[1].split("}", 1)[0]
    assert "try_files" in index
    assert "proxy_pass" not in index


@pytest.mark.parametrize("routing", [False, True, "false", "true"])
def test_v2_activation_keeps_both_v1_metadata_routes_independent(routing):
    settings = {
        **DEFAULTS,
        "packages_registry_v2_api_enabled": True,
        "packages_registry_v1_db_compat_enabled": True,
        "packages_registry_v1_db_compat_routing_enabled": routing,
    }
    nginx = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
        (ROLE / "templates/packages-registry.nginx.conf.j2").read_text()
    )
    rendered = nginx.render(settings)
    locations = rendered.split("    location ")
    for prefix in ("= /index.json {", "~ ^/modules/[a-z]"):
        location = next(block for block in locations if block.startswith(prefix))
        location = location.split("\n    }", 1)[0]
        routed = str(routing).lower() == "true"
        assert ("proxy_pass" in location) is routed
        assert ("try_files" in location) is not routed
    # The v2 service and its API proxy remain enabled with either routing choice.
    assert "Environment=PACKAGES_REGISTRY_V2_API_ENABLED=true" in TEMPLATE.render(settings)
    api = rendered.split("location ^~ /api/ {", 1)[1].split("}", 1)[0]
    assert "proxy_pass" in api


def test_every_deploy_installs_locked_db_dependencies_before_promotion_runtime_check():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    by_name = {task["name"]: task for task in tasks}
    sync = by_name["Synchronize release dependencies from frozen lockfile"]
    argv = sync["ansible.builtin.command"]["argv"]
    assert "'--extra', 'registry-db'" in argv
    assert "'--frozen'" in argv
    assert "if " not in argv
    assert "when" not in sync
    check = by_name["Verify registry promotion runtime in the deployed virtual environment"]
    assert check["ansible.builtin.command"]["argv"] == [
        "{{ packages_registry_release_path }}/.venv/bin/python",
        "-m",
        "web.backend.app.registry_promote",
        "--help",
    ]
    assert "when" not in check
    assert tasks.index(sync) < tasks.index(check)
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert config["tool"]["uv"]["package"] is False
    dependencies = config["project"]["optional-dependencies"]["registry-db"]
    for name in ("sqlalchemy", "psycopg", "alembic"):
        assert any(dep.startswith(name) and "==" in dep for dep in dependencies)


def test_production_inventory_manages_existing_v2_activation_explicitly():
    inventory = yaml.safe_load(
        (ROLE.parents[1] / "inventory/group_vars/packages_registry.yml").read_text()
    )
    assert inventory["packages_registry_v2_api_enabled"] is True
    assert inventory["packages_registry_v1_db_compat_enabled"] is True
    assert inventory["packages_registry_v1_db_compat_routing_enabled"] is True
