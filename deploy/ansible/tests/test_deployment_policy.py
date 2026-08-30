from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[3]
ANSIBLE = ROOT / "deploy" / "ansible"
ROLE = ANSIBLE / "roles" / "packages_registry"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_nginx() -> str:
    template = Environment(undefined=StrictUndefined, autoescape=False).from_string(
        read(ROLE / "templates" / "packages-registry.nginx.conf.j2")
    )
    return template.render(
        packages_registry_domain="packages.example.test",
        packages_registry_acme_webroot="/var/www/acme",
        packages_registry_certificate_name="packages.example.test",
        packages_registry_current_path="/opt/registry/current",
        packages_registry_artifact_root="/opt/registry/artifacts",
        packages_registry_nginx_site_name="packages",
        packages_registry_backend_port=8100,
        packages_registry_frontend_port=3000,
    )


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
        "packages_registry_artifact_root",
        "packages_registry_service_user",
        "packages_registry_service_group",
        "packages_registry_domain",
        "packages_registry_certificate_name",
        "packages_registry_release_retention",
        "packages_registry_min_release_free_bytes",
        "packages_registry_manage_nginx",
        "packages_registry_run_tests",
        "packages_registry_uv_version",
        "packages_registry_node_version",
        "packages_registry_pnpm_version",
        "packages_registry_backend_port",
        "packages_registry_frontend_port",
    }
    assert required <= defaults.keys()
    assert defaults["packages_registry_service_user"] != "root"
    assert defaults["packages_registry_release_retention"] >= 2
    assert defaults["packages_registry_uv_version"] == "0.12.5"
    assert defaults["packages_registry_artifact_root"] == (
        "{{ packages_registry_root }}/artifacts"
    )


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
    release_test_command = by_name["Run package registry release tests"][
        "ansible.builtin.command"
    ]
    assert release_test_command["argv"][-2:] == [
        "-m",
        "not repository_history",
    ]


def test_nginx_preserves_static_registry_and_proxies_web_application() -> None:
    nginx = render_nginx()
    assert "{{" not in nginx
    assert "server_name packages.example.test;" in nginx
    assert "root /opt/registry/current/dist;" in nginx
    assert "default_type application/json;" in nginx
    assert "alias /opt/registry/artifacts/modules/$1/$2/$1-$2.ocp;" in nginx
    assert "default_type application/octet-stream;" in nginx
    assert 'Cache-Control "public, max-age=300"' in nginx
    assert 'Cache-Control "public, max-age=31536000, immutable"' in nginx
    assert 'X-Content-Type-Options "nosniff"' in nginx
    assert "try_files $uri =404;" in nginx
    assert "autoindex off;" in nginx
    assert "ssl_certificate " in nginx
    assert "proxy_pass http://127.0.0.1:8100;" in nginx
    assert "proxy_pass http://127.0.0.1:3000;" in nginx
    assert "location ^~ /api/" in nginx
    assert "Access-Control-Allow-Origin" not in nginx
    assert "/index.html" not in nginx
    assert "autoindex on" not in nginx


def test_artifact_store_is_persistent_read_only_web_content() -> None:
    defaults = yaml.safe_load(read(ROLE / "defaults" / "main.yml"))
    tasks = read(ROLE / "tasks" / "main.yml")
    bootstrap = read(ANSIBLE / "playbooks" / "bootstrap.yml")
    artifact_root = defaults["packages_registry_artifact_root"]
    assert artifact_root == "{{ packages_registry_root }}/artifacts"
    assert "packages_registry_artifact_root.startswith(packages_registry_root ~ '/')" in tasks
    assert "not packages_registry_artifact_root.startswith(packages_registry_releases_dir" in tasks
    assert 'path: "{{ packages_registry_artifact_root }}"' in tasks
    assert 'path: "{{ packages_registry_artifact_root }}/modules"' in tasks
    assert 'mode: "0755"' in tasks
    assert 'path: "{{ packages_registry_artifact_root }}"' in bootstrap
    assert "owner: www-data" not in tasks


def test_explicit_publish_playbook_derives_target_from_registry_metadata() -> None:
    playbook = yaml.safe_load(read(ANSIBLE / "playbooks" / "publish-artifact.yml"))
    tasks_text = read(ROLE / "tasks" / "publish_artifact.yml")
    tasks = yaml.safe_load(tasks_text)
    by_name = {task["name"]: task for task in tasks}
    assert playbook[0]["roles"][0]["tasks_from"] == "publish_artifact"
    assertions = by_name["Require explicit immutable artifact publication inputs"][
        "ansible.builtin.assert"
    ]["that"]
    assert "registry_ref is match('^[0-9a-f]{40}$')" in assertions
    publish_argv = by_name[
        "Publish selected immutable artifact from reviewed Registry metadata"
    ]["ansible.builtin.command"]["argv"]
    assert "scripts/publish_artifacts.py" in publish_argv
    assert "--module" in publish_argv and "{{ module_id }}" in publish_argv
    assert "--version" in publish_argv and "{{ version }}" in publish_argv
    assert "--artifact-root" in publish_argv
    assert "target" not in " ".join(publish_argv)
    assert "--force" not in tasks_text
    assert "--overwrite" not in tasks_text
    assert "install" not in publish_argv
    assert "enable" not in publish_argv


def test_normal_deploy_bulk_publishes_exact_ready_release_before_activation() -> None:
    tasks_text = read(ROLE / "tasks" / "main.yml")
    tasks = yaml.safe_load(tasks_text)
    by_name = {task["name"]: task for task in tasks}
    publish = by_name["Publish missing reviewed artifacts from exact validated release"]
    publish_argv = publish["ansible.builtin.command"]["argv"]
    assert "--all" in publish_argv
    assert "--registry" in publish_argv
    assert "{{ packages_registry_release_path }}/registry" in publish_argv
    assert "--artifact-root" in publish_argv
    assert publish["become_user"] == "{{ packages_registry_service_user }}"
    assert "from_json" in publish["changed_when"]
    assert tasks_text.index("Mark completely validated release as ready") < tasks_text.index(
        "Publish missing reviewed artifacts from exact validated release"
    )
    assert tasks_text.index(
        "Publish missing reviewed artifacts from exact validated release"
    ) < tasks_text.index("Switch current symlink to validated SHA release atomically")


def test_newly_published_artifacts_receive_public_header_and_digest_checks() -> None:
    tasks = yaml.safe_load(read(ROLE / "tasks" / "main.yml"))
    activation = next(
        task
        for task in tasks
        if task["name"] == "Activate package registry release with rollback protection"
    )
    by_name = {task["name"]: task for task in activation["block"]}
    headers = by_name["Fetch public headers for newly published artifacts"]
    assert headers["ansible.builtin.uri"]["method"] == "HEAD"
    assert headers["loop"] == "{{ packages_registry_artifact_publication.published }}"
    header_assertions = by_name[
        "Require immutable public headers for newly published artifacts"
    ]["ansible.builtin.assert"]["that"]
    assert any("application/octet-stream" in assertion for assertion in header_assertions)
    assert any("immutable" in assertion for assertion in header_assertions)
    assert any("nosniff" in assertion for assertion in header_assertions)
    sha_check = by_name["Stream and verify public SHA for newly published artifacts"]
    assert "--verify-public" in sha_check["ansible.builtin.command"]["argv"]
    assert sha_check["loop"] == "{{ packages_registry_artifact_publication.published }}"


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


def test_release_retention_cannot_prune_persistent_artifacts() -> None:
    tasks = yaml.safe_load(read(ROLE / "tasks" / "main.yml"))
    by_name = {task["name"]: task for task in tasks}
    find_task = by_name["Find versioned package registry releases"]["ansible.builtin.find"]
    prune_task = by_name["Prune old inactive package registry releases"][
        "ansible.builtin.file"
    ]
    assert find_task["paths"] == "{{ packages_registry_releases_dir }}"
    assert prune_task["path"] == "{{ item.path }}"
    assert "packages_registry_artifact_root" not in str(find_task)
    assert "packages_registry_artifact_root" not in str(prune_task)


def test_example_inventory_contains_no_host_or_secret() -> None:
    inventory = read(ANSIBLE / "inventory" / "production.example.ini")
    assert "[packages_registry]" in inventory
    assert "example.invalid" in inventory
    assert "ansible_password" not in inventory
    assert "private_key" not in inventory
    assert "89.58." not in inventory


def test_remote_module_uploads_use_sticky_system_tmp() -> None:
    config = read(ANSIBLE / "ansible.cfg")
    assert "remote_tmp = /tmp" in config
    assert "host_key_checking = True" in config


def test_deployment_avoids_unrequested_stateful_infrastructure() -> None:
    deployment = "\n".join(
        read(path)
        for path in ANSIBLE.rglob("*")
        if path.is_file() and path.suffix in {".yml", ".j2", ".ini"}
    ).lower()
    forbidden = (
        "postgresql",
        "alembic",
        "redis",
        "docker",
    )
    for value in forbidden:
        assert value not in deployment
