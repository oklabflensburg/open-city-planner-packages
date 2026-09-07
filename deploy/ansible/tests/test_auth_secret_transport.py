"""Exercise the actual secret builder, forwarding tasks and Ansible rendering."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
ANSIBLE = ROOT / "deploy/ansible"
ROLE = ANSIBLE / "roles/packages_registry"
BUILDER = ANSIBLE / "scripts/build-github-auth-vars.py"
spec = importlib.util.spec_from_file_location(
    "auth_runtime", ROLE / "filter_plugins/auth_runtime.py"
)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def secrets():
    return {
        f"PACKAGES_AUTH_{field.upper()}": f"{field.upper()}_SECRET_TEST_SENTINEL_123456789"
        for field in contract.FIELDS
        if field in contract.REQUIRED
    }


def build(tmp_path, values):
    target = tmp_path / "auth-vars.json"
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--output", str(target)],
        env=values,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, target


@pytest.mark.parametrize("flag", ["", "false", "true", "TRUE", "yes"])
def test_activation_is_explicit_and_private(tmp_path, flag):
    values = {
        **secrets(),
        "PACKAGES_REGISTRY_AUTH_ENABLED": flag,
        "UNKNOWN_SECRET": "DO_NOT_FORWARD",
        "PACKAGES_AUTH_UNKNOWN": "DO_NOT_FORWARD",
    }
    result, path = build(tmp_path, values)
    if flag == "yes":
        assert result.returncode != 0
        assert not path.exists()
        return
    assert result.returncode == 0, result.stderr
    data = json.loads(path.read_text())
    enabled = flag.lower() == "true"
    assert data.pop("packages_registry_auth_enabled") is enabled
    assert set(data) == ({f"packages_auth_{f}" for f in contract.FIELDS} if enabled else set())
    assert path.stat().st_mode & 0o777 == 0o600
    assert "DO_NOT_FORWARD" not in path.read_text()
    assert not result.stdout and not result.stderr
    assert list(tmp_path.iterdir()) == [path]


def test_disabled_needs_no_secrets_and_ignores_invalid_unused_secrets(tmp_path):
    result, path = build(tmp_path, {"PACKAGES_AUTH_SECRET": "bad\nunused"})
    assert result.returncode == 0
    assert json.loads(path.read_text()) == {"packages_registry_auth_enabled": False}


@pytest.mark.parametrize("field", sorted(contract.REQUIRED))
def test_missing_required_fails_without_values_or_file(tmp_path, field):
    values = {**secrets(), "PACKAGES_REGISTRY_AUTH_ENABLED": "true"}
    del values[f"PACKAGES_AUTH_{field.upper()}"]
    result, path = build(tmp_path, values)
    assert result.returncode != 0
    assert f"packages_auth_{field}" in result.stderr
    assert "SENTINEL" not in result.stdout + result.stderr
    assert not path.exists()


@pytest.mark.parametrize("provider", ["github", "google"])
@pytest.mark.parametrize("half", ["client_id", "client_secret"])
def test_partial_oauth_fails_closed(tmp_path, provider, half):
    values = {
        **secrets(),
        "PACKAGES_REGISTRY_AUTH_ENABLED": "true",
        f"PACKAGES_AUTH_{provider.upper()}_{half.upper()}": "PROVIDER_SENTINEL",
    }
    result, path = build(tmp_path, values)
    assert result.returncode != 0
    assert provider in result.stderr and "SENTINEL" not in result.stderr
    assert not path.exists()


@pytest.mark.parametrize("bad", ["bad\nINJECT=true", "bad\rINJECT=true", "bad\tvalue"])
def test_builder_rejects_environment_injection(tmp_path, bad):
    result, path = build(
        tmp_path,
        {**secrets(), "PACKAGES_REGISTRY_AUTH_ENABLED": "true", "PACKAGES_AUTH_SECRET": bad},
    )
    assert result.returncode != 0
    assert bad not in result.stderr
    assert not path.exists()


def test_atomic_builder_does_not_follow_output_symlink(tmp_path):
    other = tmp_path / "untouched"
    other.write_text("unchanged")
    (tmp_path / "auth-vars.json").symlink_to(other)
    result, path = build(tmp_path, {})
    assert result.returncode == 0
    assert other.read_text() == "unchanged"
    assert not path.is_symlink()


def run_ansible(tmp_path, tasks, inputs):
    play = tmp_path / "play.yml"
    play.write_text(
        yaml.safe_dump(
            [{"hosts": "all", "gather_facts": False, "connection": "local", "tasks": tasks}]
        )
    )
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(inputs))
    input_path.chmod(0o600)
    return subprocess.run(
        [
            shutil.which("ansible-playbook"),
            "-i",
            "localhost,",
            str(play),
            "--diff",
            "--extra-vars",
            "@" + str(input_path),
        ],
        env=dict(
            os.environ, ANSIBLE_FILTER_PLUGINS=str(ROLE / "filter_plugins"), ANSIBLE_NOCOLOR="1"
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def transport_tasks(tmp_path):
    outer = yaml.safe_load((ANSIBLE / "playbooks/deploy.yml").read_text())[0]
    block = outer["tasks"][2]["block"]
    settings, auth = block[1:3]
    # Only ownership is adapted for an unprivileged local test. Production
    # ownership and filesystem guards are independently asserted below.
    auth["ansible.builtin.copy"].update(owner=str(os.getuid()), group=str(os.getgid()))
    return [settings, auth]


@pytest.mark.parametrize("enabled", [True, False])
def test_real_ansible_secret_isolation_and_disabled_preservation(tmp_path, enabled):
    database_url = "postgresql+asyncpg://auth:DATABASE_SECRET_TEST_SENTINEL@127.0.0.1/hub"
    result, ephemeral = build(
        tmp_path,
        {
            **secrets(),
            "PACKAGES_AUTH_DATABASE_URL": database_url,
            "PACKAGES_REGISTRY_AUTH_ENABLED": str(enabled).lower(),
        },
    )
    assert result.returncode == 0
    inputs = json.loads(ephemeral.read_text())
    inputs.update(
        maintenance_stage={"path": str(tmp_path)},
        packages_registry_domain="packages.example.test",
        packages_registry_auth_environment_file=str(tmp_path / "auth.env"),
    )
    (tmp_path / "auth.env").write_text("existing credential")
    tasks = transport_tasks(tmp_path)
    runtime = yaml.safe_load((ROLE / "tasks/auth_environment.yml").read_text())
    render = runtime[-1]
    render["ansible.builtin.template"].update(
        src=str(ROLE / "templates/packages-registry-auth.env.j2"),
        owner=str(os.getuid()),
        group=str(os.getgid()),
    )
    for task in (runtime[0], render):
        task["when"] = "packages_registry_auth_enabled | bool"
        tasks.append(task)
    # Public systemd artifacts also get rendered with the real role templates.
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    inputs = {**defaults, **inputs}
    for service in ("backend", "frontend"):
        tasks.append(
            {
                "ansible.builtin.template": {
                    "src": str(ROLE / f"templates/packages-registry-{service}.service.j2"),
                    "dest": str(tmp_path / f"{service}.service"),
                }
            }
        )
    run = run_ansible(tmp_path, tasks, inputs)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "SENTINEL" not in run.stdout + run.stderr
    public = (tmp_path / "settings.json").read_text()
    assert "SENTINEL" not in public and "packages_auth_" not in public
    assert json.loads(public)["packages_registry_auth_enabled"] is enabled
    for service in ("backend", "frontend"):
        assert "SENTINEL" not in (tmp_path / f"{service}.service").read_text()
    runtime_text = (tmp_path / "auth.env").read_text()
    if enabled:
        assert "SECRET_TEST_SENTINEL" in runtime_text
        assert f'AUTH_DATABASE_URL="{database_url}"' in runtime_text
        assert inputs["packages_auth_database_url"] == database_url
        assert (
            json.loads((tmp_path / "auth-vars.json").read_text())["packages_auth_database_url"]
            == database_url
        )
        assert (tmp_path / "auth.env").stat().st_mode & 0o777 == 0o600
        assert "API_BASE_URL=https://packages.example.test\n" in runtime_text
        assert 'GITHUB_CLIENT_ID=""' in runtime_text
        assert 'SMTP_USERNAME=""' in runtime_text
    else:
        assert runtime_text == "existing credential"
        assert json.loads((tmp_path / "auth-vars.json").read_text()) == {}


@pytest.mark.parametrize("partial", [False, True])
def test_direct_ansible_inputs_fail_before_render_without_leaks(tmp_path, partial):
    inputs = {
        f"packages_auth_{k.removeprefix('PACKAGES_AUTH_').lower()}": v for k, v in secrets().items()
    }
    if partial:
        inputs["packages_auth_github_client_id"] = "PROVIDER_SENTINEL"
    else:
        del inputs["packages_auth_secret"]
    inputs.update(packages_registry_auth_enabled=True, maintenance_stage={"path": str(tmp_path)})
    run = run_ansible(tmp_path, transport_tasks(tmp_path), inputs)
    assert run.returncode != 0
    assert "SENTINEL" not in run.stdout + run.stderr
    assert not (tmp_path / "auth-vars.json").exists()
    assert not (tmp_path / "auth.env").exists()


def test_runtime_guards_ownership_order_and_private_transport():
    runtime = yaml.safe_load((ROLE / "tasks/auth_environment.yml").read_text())
    assert all(t["no_log"] for t in runtime)
    render = runtime[-1]
    assert render["diff"] is False
    module = render["ansible.builtin.template"]
    assert (module["owner"], module["group"], module["mode"]) == ("root", "root", "0600")
    assert module["follow"] is False and module["unsafe_writes"] is False
    assert runtime[2]["ansible.builtin.file"]["owner"] == "root"
    guard = runtime[1]["ansible.builtin.command"]["argv"][2]
    assert "target.parents" in guard and "lstat()" in guard and "stat.S_ISREG" in guard
    main = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    env = next(t for t in main if t.get("ansible.builtin.include_tasks") == "auth_environment.yml")
    pre = next(t for t in main if t.get("ansible.builtin.include_tasks") == "auth_preflight.yml")
    assert main.index(env) < main.index(pre)
    assert env["when"] == pre["when"] == "packages_registry_auth_enabled | bool"
    outer = yaml.safe_load((ANSIBLE / "playbooks/deploy.yml").read_text())[0]
    block = outer["tasks"][2]["block"]
    auth = block[2]
    assert auth["no_log"] and auth["diff"] is False
    assert auth["ansible.builtin.copy"]["mode"] == "0600"
    assert "@auth-vars.json" in block[-1]["ansible.builtin.command"]["argv"]


def test_template_escaping_and_real_production_settings(monkeypatch):
    # Auth extras are optional in the Ansible CI job; config validation runs
    # where available, while quoting is always covered.
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters.update(contract.FilterModule().filters())
    values = {
        f"packages_auth_{field}": value
        for field, value in (
            (f, secrets().get(f"PACKAGES_AUTH_{f.upper()}", "")) for f in contract.FIELDS
        )
    }
    values["packages_auth_smtp_password"] = 'space "quote" \\ $dollar `tick` #hash ü'
    text = env.from_string((ROLE / "templates/packages-registry-auth.env.j2").read_text()).render(
        packages_auth_values=values, packages_registry_domain="packages.example.test"
    )
    assert 'SMTP_PASSWORD="space \\"quote\\" \\\\ $dollar `tick` #hash ü"' in text
    pytest.importorskip("pydantic_settings")
    from io import StringIO

    from cryptography.fernet import Fernet
    from dotenv import dotenv_values

    from web.backend.app.auth.config import Settings, get_settings
    from web.backend.app.auth.oauth import oauth_redirect_uri

    parsed = dict(dotenv_values(stream=StringIO(text), interpolate=False))
    parsed["MFA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    for key, value in parsed.items():
        monkeypatch.setenv(key, value)
    settings = Settings()
    settings.validate_security()
    get_settings.cache_clear()
    assert oauth_redirect_uri("github") == (
        "https://packages.example.test/api/v1/auth/oauth/github/callback"
    )
    get_settings.cache_clear()


def test_complete_optional_providers_and_smtp_credentials(tmp_path):
    values = {**secrets(), "PACKAGES_REGISTRY_AUTH_ENABLED": "true"}
    for field in (
        "github_client_id",
        "github_client_secret",
        "google_client_id",
        "google_client_secret",
        "smtp_username",
        "smtp_password",
    ):
        values[f"PACKAGES_AUTH_{field.upper()}"] = f"{field}_SENTINEL"
    result, path = build(tmp_path, values)
    assert result.returncode == 0
    assert not result.stdout + result.stderr
    generated = json.loads(path.read_text())
    for key, value in values.items():
        if key.startswith("PACKAGES_AUTH_"):
            assert generated[key.lower()] == value
