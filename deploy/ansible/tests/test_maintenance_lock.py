"""Real processes exercise the same flock implementation used on the target."""

import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest
import yaml

FILES = Path(__file__).resolve().parents[1] / "roles/packages_registry/files"
sys.path.insert(0, str(FILES))
import maintenance_lock as maintenance  # noqa: E402


def ready(process):
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=10), "lock owner never became ready"
        assert process.stdout.readline().strip() == "ready"
    finally:
        selector.close()


@pytest.fixture
def owner(tmp_path):
    processes = []

    def start(code=None):
        code = code or "print('ready', flush=True); sys.stdin.read()"
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys; from pathlib import Path; "
                    f"sys.path.insert(0, {str(FILES)!r}); "
                    "from maintenance_lock import exclusive_lock; "
                    f"lock = exclusive_lock(Path({str(tmp_path / 'maintenance.lock')!r})); "
                    f"lock.__enter__(); {code}"
                ),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(process)
        ready(process)
        return process

    yield start
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_first_acquisition_persistent_inode_and_legacy_directory(tmp_path):
    old = tmp_path / "lock"
    old.mkdir()
    lock = tmp_path / "maintenance.lock"
    with maintenance.exclusive_lock(lock):
        inode = lock.stat().st_ino
        assert lock.stat().st_mode & 0o777 == 0o600
    with maintenance.exclusive_lock(lock):
        assert lock.stat().st_ino == inode
    assert old.is_dir()  # No unsafe attempt to break an old owner's directory.
    assert maintenance.run([sys.executable, "-c", "pass"], lock) == 0


def test_parallel_deploy_refuses_and_flock_cli_uses_same_authority(tmp_path, owner, capsys):
    owner()
    lock = tmp_path / "maintenance.lock"
    assert maintenance.run([sys.executable, "-c", "raise Exception('must not run')"], lock) == 75
    assert "busy" in capsys.readouterr().err
    result = subprocess.run(["flock", "-n", "-E", "75", str(lock), "true"], check=False)
    assert result.returncode == 75


@pytest.mark.parametrize("termination", ["normal", "terminate", "kill"])
def test_exit_and_crash_release_without_deleting_file(tmp_path, owner, termination):
    process = owner()
    lock = tmp_path / "maintenance.lock"
    with pytest.raises(maintenance.LockBusy), maintenance.exclusive_lock(lock):
        pytest.fail("parallel lock acquired")
    if termination == "normal":
        process.communicate(input="", timeout=10)
        assert process.returncode == 0
    else:
        getattr(process, termination)()
        process.communicate(timeout=10)
    assert lock.is_file()
    with maintenance.exclusive_lock(lock):
        pass


def test_cleanup_defers_during_deploy_and_then_runs(tmp_path, owner, monkeypatch, capsys):
    import prune_releases

    process = owner()
    monkeypatch.setattr(prune_releases, "LOCK", tmp_path / "maintenance.lock")
    monkeypatch.setattr(
        sys, "argv", ["cleanup", "--release-root", str(tmp_path), "--retention", "5"]
    )
    called = []
    monkeypatch.setattr(prune_releases, "prune", lambda *args: called.append(args) or [])
    assert prune_releases.main() == 0
    assert not called
    assert "deferred" in capsys.readouterr().out
    process.kill()
    process.communicate(timeout=10)
    assert prune_releases.main() == 0
    assert len(called) == 1


def test_cleanup_and_deploy_import_identical_lock_authority():
    import prune_releases

    assert prune_releases.LOCK == maintenance.LOCK
    assert prune_releases.exclusive_lock is maintenance.exclusive_lock
    assert Path("/var/lib/ocp-packages-maintenance/maintenance.lock") == maintenance.LOCK


def test_unsafe_lock_symlink_fails_closed(tmp_path):
    target = tmp_path / "other"
    target.write_text("untouched")
    lock = tmp_path / "maintenance.lock"
    lock.symlink_to(target)
    assert maintenance.run(["true"], lock) == 1
    assert target.read_text() == "untouched"


def test_child_retains_lock_if_only_supervisor_is_killed(tmp_path):
    lock = tmp_path / "maintenance.lock"
    child_code = "import sys; print('ready', flush=True); sys.stdin.read()"
    code = (
        f"import sys; sys.path.insert(0, {str(FILES)!r}); from pathlib import Path; "
        "from maintenance_lock import run; "
        f"sys.exit(run([sys.executable, '-c', {child_code!r}], Path({str(lock)!r})))"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        ready(process)
        process.kill()
        process.wait(timeout=10)
        with pytest.raises(maintenance.LockBusy), maintenance.exclusive_lock(lock):
            pytest.fail("surviving work lost the lock")
        # EOF terminates the inherited-fd child even though its supervisor died.
        process.communicate(input="", timeout=10)
        with maintenance.exclusive_lock(lock):
            pass
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)


def test_active_pre_migration_cleanup_is_refused(tmp_path):
    old = tmp_path / "ocp-packages-prune-releases"
    old.write_text("import sys; print('ready', flush=True); sys.stdin.read()")
    process = subprocess.Popen(
        [sys.executable, str(old)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        ready(process)
        with pytest.raises(RuntimeError, match="still running"):
            maintenance.check_legacy_cleanup()
    finally:
        process.communicate(input="", timeout=10)
    maintenance.check_legacy_cleanup()


def forwarding_task():
    outer = yaml.safe_load((FILES.parents[2] / "playbooks/deploy.yml").read_text())[0]
    task = outer["tasks"][2]["block"][1]
    assert task["no_log"] is True
    assert task["ansible.builtin.copy"]["mode"] == "0600"
    return task


def run_forwarding(tmp_path, play, inventory, extra=None):
    ansible = shutil.which("ansible-playbook")
    assert ansible, "Install the locked development dependencies"
    play_path = tmp_path / "forward.yml"
    play_path.write_text(yaml.safe_dump([play]))
    inventory_path = tmp_path / "inventory.yml"
    inventory_path.write_text(yaml.safe_dump(inventory))
    result = subprocess.run(
        [ansible, "-i", str(inventory_path), str(play_path), "-e", json.dumps(extra or {})],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        # Explicitly enable warnings so a user/controller setting cannot mask regression.
        env=dict(os.environ, ANSIBLE_DEPRECATION_WARNINGS="true", ANSIBLE_NOCOWS="true"),
    )
    output = result.stdout + result.stderr
    assert "play_hosts" not in output, output
    assert "DEPRECATION WARNING" not in output, output
    return result, output


@pytest.mark.parametrize(
    "winner", ["default", "inventory", "host", "play", "vars_file", "fact", "extra"]
)
def test_forwarded_inventory_settings_keep_precedence(tmp_path, winner):
    """Resolve the real task against Ansible's precedence, not a simulated merge."""
    sources = ["default", "inventory", "host", "play", "vars_file", "fact", "extra"]
    active = sources[: sources.index(winner) + 1]
    key = "packages_registry_precedence_test"
    role = tmp_path / "roles/forwarding_fixture"
    (role / "defaults").mkdir(parents=True)
    (role / "tasks").mkdir()
    (role / "defaults/main.yml").write_text(yaml.safe_dump({key: "default"}))
    (role / "tasks/main.yml").write_text("[]\n")
    group_vars = {
        "packages_registry_root": "/tmp/example",
        "packages_registry_repo_path": "{{ packages_registry_root }}/repo",
        "packages_registry_child": "{{ packages_registry_root }}/child",
        "packages_registry_v2_api_enabled": True,
        "packages_registry_v1_db_compat_enabled": True,
        "packages_registry_v1_db_compat_routing_enabled": True,
        "ansible_password": "NOT_A_SECRET_TEST_SENTINEL",
        "ansible_user": "fixture-local-user",
        "ansible_ssh_private_key_file": "/unused/fixture-key",
        "ansible_ssh_common_args": "-o BatchMode=yes",
        "unrelated": "{{ intentionally_undefined_non_registry_value }}",
        "other_packages_registry_unselected": "excluded",
    }
    if "inventory" in active:
        group_vars[key] = "inventory"
    host_vars = {"ansible_host": "127.0.0.1"}
    if "host" in active:
        host_vars[key] = "host"
    inventory = {"all": {"hosts": {"localhost": host_vars}, "vars": group_vars}}
    play = {
        "hosts": "all",
        "connection": "local",
        "gather_facts": False,
        "roles": ["forwarding_fixture"],
        "vars": {
            "maintenance_stage": {"path": str(tmp_path)},
            "packages_registry_enabled": False,
            "packages_registry_port": 8100,
            "packages_registry_string": "8100",
            "packages_registry_names": ["foo", "bar"],
            "packages_registry_options": {
                "mode": "strict",
                "port": 8100,
                "path": "{{ packages_registry_child }}",
            },
            "packages_registry_optional": None,
        },
        "tasks": [],
    }
    if "play" in active:
        play["vars"][key] = "play"
    if "vars_file" in active:
        values_file = tmp_path / "values.yml"
        values_file.write_text(yaml.safe_dump({key: "vars_file"}))
        play["vars_files"] = [str(values_file)]
    if "fact" in active:
        play["tasks"].append({"ansible.builtin.set_fact": {key: "fact"}})
    extra = {"packages_registry_deploy_ref": "abc"}
    if "extra" in active:
        extra[key] = "extra"
    # The normal Jinja reference and targeted lookup must agree in this exact host context.
    play["tasks"].extend(
        [
            {
                "ansible.builtin.assert": {
                    "that": [f"{key} == '{winner}'", "ansible_version.full == '2.19.12'"]
                }
            },
            forwarding_task(),
        ]
    )
    result, output = run_forwarding(tmp_path, play, inventory, extra)
    assert result.returncode == 0, output
    settings = tmp_path / "settings.json"
    values = json.loads(settings.read_text())
    assert settings.stat().st_mode & 0o777 == 0o600
    assert values == {
        key: winner,
        "packages_registry_root": "/tmp/example",
        "packages_registry_repo_path": "/tmp/example/repo",
        "packages_registry_child": "/tmp/example/child",
        "packages_registry_v2_api_enabled": True,
        "packages_registry_v1_db_compat_enabled": True,
        "packages_registry_v1_db_compat_routing_enabled": True,
        "packages_registry_deploy_ref": "abc",
        "packages_registry_enabled": False,
        "packages_registry_port": 8100,
        "packages_registry_string": "8100",
        "packages_registry_names": ["foo", "bar"],
        "packages_registry_options": {"mode": "strict", "port": 8100, "path": "/tmp/example/child"},
        "packages_registry_optional": None,
    }
    assert type(values["packages_registry_enabled"]) is bool
    assert type(values["packages_registry_port"]) is int


@pytest.mark.parametrize("broken", [False, True])
def test_forwarding_empty_allowlist_and_unresolved_value(tmp_path, broken):
    play = {
        "hosts": "all",
        "connection": "local",
        "gather_facts": False,
        "vars": {"maintenance_stage": {"path": str(tmp_path)}},
        "tasks": [forwarding_task()],
    }
    if broken:
        play["vars"]["packages_registry_broken"] = "{{ intentionally_missing_registry_value }}"
    result, output = run_forwarding(tmp_path, play, {"all": {"hosts": {"localhost": {}}}})
    settings = tmp_path / "settings.json"
    if broken:
        assert result.returncode != 0
        assert "Forward resolved registry settings without SSH credentials" in output
        assert not settings.exists()
    else:
        assert result.returncode == 0, output
        assert json.loads(settings.read_text()) == {}


def test_whole_local_ansible_run_and_rescue_hold_lock(tmp_path):
    ansible = shutil.which("ansible-playbook")
    assert ansible
    lock = tmp_path / "maintenance.lock"
    probe = (
        "import fcntl, sys; "
        "fd = open(sys.argv[1], 'a'); "
        "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)"
    )
    check = {
        "ansible.builtin.command": {"argv": [sys.executable, "-c", probe, str(lock)]},
        "register": "probe",
        "failed_when": "probe.rc == 0",
        "changed_when": False,
    }
    play = [
        {
            "hosts": "all",
            "connection": "local",
            "gather_facts": False,
            "tasks": [
                {
                    "block": [check, {"ansible.builtin.fail": {"msg": "exercise rollback"}}],
                    "rescue": [
                        check,
                        {
                            "ansible.builtin.copy": {
                                "dest": str(tmp_path / "rolled-back"),
                                "content": "yes",
                            }
                        },
                    ],
                }
            ],
        }
    ]
    play_path = tmp_path / "harmless.yml"
    play_path.write_text(yaml.safe_dump(play))
    assert maintenance.run([ansible, "-i", "localhost,", str(play_path)], lock) == 0
    assert (tmp_path / "rolled-back").read_text() == "yes"
    with maintenance.exclusive_lock(lock):
        pass


def test_running_cleanup_excludes_deploy_then_crash_releases(tmp_path):
    lock = tmp_path / "maintenance.lock"
    code = (
        f"import sys; sys.path.insert(0, {str(FILES)!r}); "
        "import prune_releases as p; from pathlib import Path; "
        f"p.LOCK = Path({str(lock)!r}); "
        "p.prune = lambda *args: (print('ready', flush=True), sys.stdin.read(), [])[2]; "
        "sys.argv = ['cleanup', '--release-root', '/unused', '--retention', '5']; "
        "sys.exit(p.main())"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready(process)
        assert maintenance.run(["true"], lock) == maintenance.BUSY
    finally:
        process.kill()
        process.communicate(timeout=10)
    assert maintenance.run(["true"], lock) == 0


def test_command_failure_releases_lock_and_preserves_status(tmp_path):
    lock = tmp_path / "maintenance.lock"
    assert maintenance.run([sys.executable, "-c", "raise SystemExit(23)"], lock) == 23
    assert maintenance.run(["true"], lock) == 0


def test_ansible_crash_keeps_surviving_task_locked_until_it_finishes(tmp_path):
    """Kill the real Ansible parent mid-task; its worker must retain the fd."""
    ansible = shutil.which("ansible-playbook")
    assert ansible
    lock = tmp_path / "maintenance.lock"
    started, release = tmp_path / "started", tmp_path / "release"
    work = (
        f"from pathlib import Path; import time; Path({str(started)!r}).touch()\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(0.02)\n"
    )
    play = [
        {
            "hosts": "all",
            "connection": "local",
            "gather_facts": False,
            "tasks": [{"ansible.builtin.command": {"argv": [sys.executable, "-c", work]}}],
        }
    ]
    play_path = tmp_path / "surviving-task.yml"
    play_path.write_text(yaml.safe_dump(play))
    code = (
        f"import sys; sys.path.insert(0, {str(FILES)!r}); "
        "from pathlib import Path; from maintenance_lock import run; "
        f"sys.exit(run({[ansible, '-i', 'localhost,', str(play_path)]!r}, Path({str(lock)!r})))"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started.exists(), "Ansible task did not start"
        children = Path(f"/proc/{process.pid}/task/{process.pid}/children").read_text().split()
        assert len(children) == 1
        os.kill(int(children[0]), signal.SIGKILL)
        process.wait(timeout=10)
        with pytest.raises(maintenance.LockBusy), maintenance.exclusive_lock(lock):
            pytest.fail("surviving Ansible task lost the lock")
        release.touch()
        process.communicate(timeout=15)
        acquired = subprocess.run(["flock", "-w", "10", str(lock), "true"], check=False, timeout=15)
        assert acquired.returncode == 0, "orphaned Ansible worker retained the lock"
        with maintenance.exclusive_lock(lock):
            pass
    finally:
        release.touch()
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)


@pytest.mark.parametrize("auth_enabled", [False, True])
def test_outer_playbook_stages_runs_async_and_removes_completed_invocation(tmp_path, auth_enabled):
    """Run the orchestration locally with harmless work and preinstalled Ansible."""
    ansible = shutil.which("ansible-playbook")
    assert ansible
    ansible_root = FILES.parents[2]
    maintenance_root = tmp_path / "maintenance"
    maintenance_root.mkdir()
    (maintenance_root / "lock").mkdir()  # The incident's leftover mkdir lock.
    lock = maintenance_root / "maintenance.lock"
    fixture_roles = tmp_path / "roles"
    fixture_files = fixture_roles / "packages_registry/files"
    fixture_files.mkdir(parents=True)
    script = (FILES / "maintenance_lock.py").read_text().replace(str(maintenance.LOCK), str(lock))
    (fixture_files / "maintenance_lock.py").write_text(script)
    inner = tmp_path / "harmless-inner.yml"
    inner.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "all",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {
                            "ansible.builtin.command": {
                                "argv": ["flock", "-n", "-E", "75", str(lock), "true"]
                            },
                            "register": "attempt",
                            "failed_when": "attempt.rc != 75",
                            "changed_when": False,
                        },
                        {
                            "ansible.builtin.assert": {
                                "that": ["packages_registry_v2_api_enabled | bool"]
                            }
                        },
                        {
                            "ansible.builtin.copy": {
                                "dest": str(tmp_path / "executed"),
                                "content": "yes",
                            }
                        },
                    ],
                }
            ]
        )
    )
    outer = yaml.safe_load((ansible_root / "playbooks/deploy.yml").read_text())[0]
    outer.update(hosts="all", connection="local", become=False, gather_facts=False)
    outer["vars"]["packages_registry_v2_api_enabled"] = True
    outer["vars"]["packages_registry_auth_enabled"] = auth_enabled
    if auth_enabled:
        for field in (
            "database_url", "secret", "oauth_state_secret", "mfa_recovery_pepper",
            "mfa_encryption_key", "redis_url", "smtp_host", "smtp_from_email",
        ):
            outer["vars"][f"packages_auth_{field}"] = f"{field}_SECRET_TEST_SENTINEL"
    inner_play = yaml.safe_load(inner.read_text())[0]
    inner_play["tasks"].append({
        "ansible.builtin.assert": {"that": [
            "packages_auth_secret == 'secret_SECRET_TEST_SENTINEL'" if auth_enabled
            else "packages_auth_secret is undefined",
            "'SENTINEL' not in lookup('file', 'settings.json')",
            "'packages_auth_' not in lookup('file', 'settings.json')",
        ]},
        "no_log": True,
    })
    inner.write_text(yaml.safe_dump([inner_play]))
    tasks = outer["tasks"]
    parent = tasks[0]["ansible.builtin.file"]
    parent.update(path=str(maintenance_root))
    del parent["owner"], parent["group"]
    tasks[1]["ansible.builtin.tempfile"]["path"] = str(maintenance_root)
    block = tasks[2]["block"]
    block[0]["ansible.builtin.copy"].update(owner=str(os.getuid()), group=str(os.getgid()))
    block[0]["loop"] = [
        {"src": str(fixture_roles) + "/", "dest": "roles/"},
        {"src": str(inner), "dest": "deploy_locked.yml"},
        {"src": str(ansible_root / "ansible.cfg"), "dest": "ansible.cfg"},
    ]
    secret_stage = block[2]["ansible.builtin.copy"]
    secret_stage.update(owner=str(os.getuid()), group=str(os.getgid()))
    # Dependency download is deliberately excluded; exercise real local Ansible,
    # the unchanged async command, settings handoff and completion cleanup tasks.
    block[3] = {
        "ansible.builtin.file": {
            "src": str(Path(ansible).parent.parent),
            "dest": "{{ maintenance_stage.path }}/venv",
            "state": "link",
        }
    }
    block[4] = {"ansible.builtin.debug": {"msg": "Using locked test environment"}}
    play = tmp_path / "outer.yml"
    play.write_text(yaml.safe_dump([outer]))
    result = subprocess.run(
        [ansible, "-i", "localhost,", str(play)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(
            ansible_root / "roles/packages_registry/filter_plugins")),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SENTINEL" not in result.stdout + result.stderr
    assert (tmp_path / "executed").read_text() == "yes"
    assert not list(maintenance_root.glob("deploy-*"))
    assert (maintenance_root / "lock").is_dir()
    with maintenance.exclusive_lock(lock):
        pass
