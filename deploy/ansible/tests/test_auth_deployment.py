"""Auth gates must not become a credential transport or alter Registry activation."""

from pathlib import Path

import jinja2
import pytest
import yaml

ROLE = Path(__file__).resolve().parents[1] / "roles/packages_registry"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text())


def render(name, enabled):
    return (
        jinja2.Environment(undefined=jinja2.StrictUndefined)
        .from_string((ROLE / "templates" / name).read_text())
        .render({**DEFAULTS, "packages_registry_auth_enabled": enabled})
    )


@pytest.mark.parametrize("enabled", [False, "false", True, "true"])
def test_independent_auth_activation_and_no_frontend_secrets(enabled):
    active = str(enabled).lower() == "true"
    backend = render("packages-registry-backend.service.j2", enabled)
    frontend = render("packages-registry-frontend.service.j2", enabled)
    assert ("EnvironmentFile=/etc/open-city-planner-packages/auth.env" in backend) is active
    assert f"Environment=NUXT_PUBLIC_AUTH_ENABLED={str(active).lower()}" in frontend
    assert "ProtectHome=true" in backend.splitlines()
    assert "EnvironmentFile=" not in frontend
    assert "SECRET" not in frontend and "PASSWORD" not in frontend
    assert "UnsetEnvironment=PACKAGES_REGISTRY_V2_API_ENABLED" in backend
    assert "UnsetEnvironment=PACKAGES_REGISTRY_V1_DB_COMPAT_ENABLED" in backend
    if not active:
        assert "UnsetEnvironment=AUTH_ENABLED" in backend


def test_auth_preflight_is_private_read_only_and_before_activation():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    preflight = next(t for t in tasks if t["name"] == "Check opt-in auth production prerequisites")
    activate = next(
        t
        for t in tasks
        if t["name"] == "Activate package registry release with rollback protection"
    )
    assert tasks.index(preflight) < tasks.index(activate)
    assert preflight["when"] == "packages_registry_auth_enabled | bool"
    private = yaml.safe_load((ROLE / "tasks/auth_preflight.yml").read_text())
    assert all(t["no_log"] for t in private)
    assert private[0]["ansible.builtin.stat"]["follow"] is False
    argv = private[-1]["ansible.builtin.command"]["argv"]
    assert "--property=EnvironmentFile={{ packages_registry_auth_environment_file }}" in argv
    assert "web.backend.app.auth.preflight" in argv
    assert not any("SECRET=" in a or "PASSWORD=" in a for a in argv)
    assert "slurp" not in (ROLE / "tasks/auth_preflight.yml").read_text()
    assert "settings.json" not in (ROLE / "tasks/auth_preflight.yml").read_text()
    assert any(
        t["name"] == "Require healthy auth before proxy activation" for t in activate["block"]
    )


def test_auth_urls_do_not_log_bearer_query_parameters():
    nginx = render("packages-registry.nginx.conf.j2", True)
    auth = nginx.split("location ^~ /api/v1/auth/ {", 1)[1].split("}", 1)[0]
    assert "access_log off;" in auth
    email = nginx.split("location ~ ^/(email-bestaetigen", 1)[1].split("}", 1)[0]
    assert "access_log off;" in email
