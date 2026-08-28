from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
ANSIBLE = ROOT / "deploy" / "ansible"
ROLE = ANSIBLE / "roles" / "packages_registry"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_all_ansible_yaml_is_parseable() -> None:
    yaml_files = [
        *ANSIBLE.glob("playbooks/*.yml"),
        *ANSIBLE.glob("inventory/group_vars/*.yml"),
        *ROLE.glob("defaults/*.yml"),
        *ROLE.glob("tasks/*.yml"),
        *ROLE.glob("handlers/*.yml"),
    ]
    assert yaml_files
    for path in yaml_files:
        assert yaml.safe_load(read(path)) is not None, path


def test_role_structure_and_required_defaults() -> None:
    defaults = yaml.safe_load(read(ROLE / "defaults" / "main.yml"))
    assert (ROLE / "tasks" / "main.yml").is_file()
    assert (ROLE / "handlers" / "main.yml").is_file()
    assert (ROLE / "templates" / "packages-registry.nginx.conf.j2").is_file()
    required = {
        "packages_registry_repo_url",
        "packages_registry_repo_path",
        "packages_registry_deploy_ref",
        "packages_registry_root",
        "packages_registry_releases_dir",
        "packages_registry_current_path",
        "packages_registry_service_user",
        "packages_registry_service_group",
        "packages_registry_domain",
        "packages_registry_certificate_name",
        "packages_registry_release_retention",
        "packages_registry_min_release_free_bytes",
        "packages_registry_manage_nginx",
        "packages_registry_run_tests",
        "packages_registry_uv_version",
    }
    assert required <= defaults.keys()
    assert defaults["packages_registry_service_user"] != "root"
    assert defaults["packages_registry_release_retention"] >= 2
    assert defaults["packages_registry_uv_version"] == "0.12.5"


def test_immutable_release_is_built_before_atomic_activation() -> None:
    tasks = read(ROLE / "tasks" / "main.yml")
    assert "force: false" in tasks
    assert "git archive --format=tar" in tasks
    assert "^[0-9a-f]{40}$" in tasks
    assert ".release-ready" in tasks
    assert tasks.index("Synchronize release dependencies from frozen lockfile") < tasks.index(
        "Switch current symlink to validated SHA release atomically"
    )
    assert tasks.index("Build deterministic package registry distribution") < tasks.index(
        "Switch current symlink to validated SHA release atomically"
    )
    assert "state: link" in tasks
    assert "force: true" in tasks


def test_validation_gates_are_mandatory_except_test_suite() -> None:
    tasks = yaml.safe_load(read(ROLE / "tasks" / "main.yml"))
    by_name = {task["name"]: task for task in tasks}
    required_tasks = (
        "Lint package registry release",
        "Validate package registry source",
        "Build deterministic package registry distribution",
        "Verify deterministic distribution matches release commit",
        "Check release whitespace against release commit",
        "Require non-empty regular package registry index",
    )
    for name in required_tasks:
        assert "when" not in by_name[name]
    assert by_name["Run package registry release tests"]["when"] == (
        "packages_registry_run_tests | bool"
    )


def test_nginx_is_static_tls_only_with_required_headers() -> None:
    nginx = read(ROLE / "templates" / "packages-registry.nginx.conf.j2")
    assert "server_name {{ packages_registry_domain }};" in nginx
    assert "root {{ packages_registry_current_path }}/dist;" in nginx
    assert "default_type application/json;" in nginx
    assert 'Cache-Control "public, max-age=300"' in nginx
    assert 'X-Content-Type-Options "nosniff"' in nginx
    assert "try_files $uri =404;" in nginx
    assert "autoindex off;" in nginx
    assert "ssl_certificate " in nginx
    assert "proxy_pass" not in nginx
    assert "Access-Control-Allow-Origin" not in nginx
    assert "/index.html" not in nginx


def test_bootstrap_uses_pinned_uv_without_download_script() -> None:
    bootstrap = read(ANSIBLE / "playbooks" / "bootstrap.yml")
    tasks = read(ROLE / "tasks" / "main.yml")
    defaults = yaml.safe_load(read(ROLE / "defaults" / "main.yml"))
    assert defaults["packages_registry_uv_version"] == "0.12.5"
    assert '"uv=={{ packages_registry_uv_version }}"' in bootstrap
    assert "stdout.startswith(" in bootstrap
    assert "stdout.startswith(" in tasks
    assert "curl" not in bootstrap
    assert "| sh" not in bootstrap


def test_nginx_validation_smoke_rollback_and_retention_are_present() -> None:
    tasks = read(ROLE / "tasks" / "main.yml")
    handlers = read(ROLE / "handlers" / "main.yml")
    assert "Activate package registry release with rollback protection" in tasks
    assert "rescue:" in tasks
    assert "Preserve original package registry deployment failure" in tasks
    assert "Restore previous package registry release symlink" in tasks
    assert "Remove failed first-deploy current symlink" in tasks
    assert "Verify previous Registry v1 release after rollback" in tasks
    assert "https://127.0.0.1/index.json" in tasks
    assert "validate_certs: true" in tasks
    assert "Select old inactive package registry releases by mtime" in tasks
    assert "packages_registry_protected_release_paths" in tasks
    assert "nginx" in handlers and "-t" in handlers
    assert handlers.index("Validate nginx configuration") < handlers.index("Reload nginx")


def test_example_inventory_contains_no_host_or_secret() -> None:
    inventory = read(ANSIBLE / "inventory" / "production.example.ini")
    assert "[packages_registry]" in inventory
    assert "example.invalid" in inventory
    assert "ansible_password" not in inventory
    assert "private_key" not in inventory
    assert "89.58." not in inventory


def test_deployment_does_not_add_an_application_runtime() -> None:
    deployment = "\n".join(
        read(path)
        for path in ANSIBLE.rglob("*")
        if path.is_file() and path.suffix in {".yml", ".j2", ".ini"}
    ).lower()
    forbidden = (
        "proxy_pass",
        "packages-registry.service",
        "fastapi",
        "postgresql",
        "alembic",
        "redis",
        "docker",
        "nodejs",
        ".ocp",
    )
    for value in forbidden:
        assert value not in deployment
