from pathlib import Path

import jinja2

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "roles/packages_registry/templates/packages-registry.nginx.conf.j2"
)


def render(value):
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    template = environment.from_string(TEMPLATE.read_text())
    return template.render(
        packages_registry_domain="packages.example.test",
        packages_registry_acme_webroot="/var/www/acme",
        packages_registry_certificate_name="packages.example.test",
        packages_registry_current_path="/opt/registry/current",
        packages_registry_artifact_root="/opt/registry/artifacts",
        packages_registry_backend_port=8100,
        packages_registry_frontend_port=3000,
        packages_registry_v1_db_compat_routing_enabled=value,
    )


def index_location(rendered):
    return rendered.split("location = /index.json {", 1)[1].split("}", 1)[0]


def test_string_false_does_not_enable_database_routing():
    index = index_location(render("false"))
    assert "proxy_pass" not in index
    assert "try_files" in index


def test_string_true_enables_database_routing():
    index = index_location(render("true"))
    assert "proxy_pass" in index
    assert "try_files" not in index
