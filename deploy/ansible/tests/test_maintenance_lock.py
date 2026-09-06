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


def test_forwarded_inventory_settings_keep_precedence(tmp_path):
    """Execute the real settings task: production overrides must not become defaults."""
    ansible = shutil.which("ansible-playbook")
    assert ansible, "Install the locked development dependencies"
    outer = yaml.safe_load((FILES.parents[2] / "playbooks/deploy.yml").read_text())[0]
    task = outer["tasks"][2]["block"][1]
    play = [
        {
            "hosts": "all",
            "connection": "local",
            "gather_facts": False,
            "vars": {"maintenance_stage": {"path": str(tmp_path)}},
            "tasks": [task],
        }
    ]
    play_path = tmp_path / "forward.yml"
    play_path.write_text(yaml.safe_dump(play))
    inventory = tmp_path / "inventory.yml"
    inventory.write_text(
        yaml.safe_dump(
            {
                "all": {
                    "hosts": {"localhost": {}},
                    "vars": {
                        "packages_registry_root": "/custom/root",
                        "packages_registry_repo_path": "{{ packages_registry_root }}/repo",
                        "packages_registry_v2_api_enabled": True,
                        "packages_registry_v1_db_compat_enabled": True,
                        "packages_registry_v1_db_compat_routing_enabled": True,
                        "ansible_password": "NOT_A_SECRET_TEST_SENTINEL",
                    },
                }
            }
        )
    )
    result = subprocess.run(
        [ansible, "-i", str(inventory), str(play_path), "-e", "packages_registry_deploy_ref=abc"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    values = json.loads((tmp_path / "settings.json").read_text())
    assert values == {
        "packages_registry_root": "/custom/root",
        "packages_registry_repo_path": "/custom/root/repo",
        "packages_registry_v2_api_enabled": True,
        "packages_registry_v1_db_compat_enabled": True,
        "packages_registry_v1_db_compat_routing_enabled": True,
        "packages_registry_deploy_ref": "abc",
    }


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


def test_outer_playbook_stages_runs_async_and_removes_completed_invocation(tmp_path):
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
    # Dependency download is deliberately excluded; exercise real local Ansible,
    # the unchanged async command, settings handoff and completion cleanup tasks.
    block[2] = {
        "ansible.builtin.file": {
            "src": str(Path(ansible).parent.parent),
            "dest": "{{ maintenance_stage.path }}/venv",
            "state": "link",
        }
    }
    block[3] = {"ansible.builtin.debug": {"msg": "Using locked test environment"}}
    play = tmp_path / "outer.yml"
    play.write_text(yaml.safe_dump([outer]))
    result = subprocess.run(
        [ansible, "-i", "localhost,", str(play)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "executed").read_text() == "yes"
    assert not list(maintenance_root.glob("deploy-*"))
    assert (maintenance_root / "lock").is_dir()
    with maintenance.exclusive_lock(lock):
        pass
