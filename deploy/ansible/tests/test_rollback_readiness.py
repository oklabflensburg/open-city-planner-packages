"""Execute the real rollback task sequence with isolated HTTP processes and files."""

import copy
import json
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
import yaml

TASKS = Path(__file__).resolve().parents[1] / "roles/packages_registry/tasks/main.yml"


def rollback_tasks():
    tasks = yaml.safe_load(TASKS.read_text())
    activation = next(task for task in tasks if "rescue" in task)
    return copy.deepcopy(activation["rescue"])


def test_rollback_readiness_is_bounded_and_precedes_nginx():
    tasks = rollback_tasks()[1]["block"]
    names = [task["name"] for task in tasks]
    readiness = next(task for task in tasks if "until" in task)
    assert readiness["retries"] == 10
    assert readiness["delay"] == 2
    assert readiness["until"] == "packages_registry_rollback_process_smoke.status == 200"
    assert readiness["when"] == "packages_registry_previous_release_path | length > 0"
    assert readiness["loop"] == [
        {"url": "http://127.0.0.1:{{ packages_registry_backend_port }}/api/v1/health"},
        {"url": "http://127.0.0.1:{{ packages_registry_frontend_port }}/"},
    ]
    ordered = [
        "Restore previous package registry release symlink",
        "Restart package explorer services after rollback",
        readiness["name"],
        "Validate nginx configuration after rollback",
        "Reload nginx after rollback",
        "Verify previous Registry v1 release after rollback",
    ]
    assert [names.index(name) for name in ordered] == sorted(names.index(name) for name in ordered)
    assert "ignore_errors" not in TASKS.read_text()
    assert "ansible.builtin.pause" not in TASKS.read_text()


@pytest.mark.parametrize("unhealthy", [None, "backend", "frontend"])
def test_real_rollback_retries_before_vhost_and_fails_closed(tmp_path, unhealthy):
    ansible = shutil.which("ansible-playbook")
    assert ansible, "Install the locked development dependencies"
    previous, failed = tmp_path / "previous-release", tmp_path / "failed-release"
    previous.mkdir()
    failed.mkdir()
    current = tmp_path / "current"
    current.symlink_to(failed)
    events = tmp_path / "events"
    counts = {"backend": 0, "frontend": 0}
    healthy = set()

    def handler(kind):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with events.open("a") as stream:
                    stream.write(f"{kind}:{self.path}\n")
                if self.path == "/index.json":
                    self.send_response(200 if healthy == {"backend", "frontend"} else 502)
                    payload = {"schema_version": 1, "modules": []}
                else:
                    counts[kind] += 1
                    # First backend request fails at transport level, like a listener
                    # that has not come up yet. Subsequent requests can become ready.
                    if kind == "backend" and counts[kind] == 1:
                        self.close_connection = True
                        return
                    status = 503 if unhealthy == kind else 200
                    self.send_response(status)
                    if status == 200:
                        healthy.add(kind)
                    payload = {"status": "ok"}
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, *_args):
                pass

        return Handler

    backend = ThreadingHTTPServer(("127.0.0.1", 0), handler("backend"))
    frontend = ThreadingHTTPServer(("127.0.0.1", 0), handler("frontend"))
    threads = [Thread(target=server.serve_forever, daemon=True) for server in (backend, frontend)]
    for thread in threads:
        thread.start()

    tasks = rollback_tasks()
    # Preserve the actual restore, URI retries, conditionals and failure reporting.
    # Replace host service/nginx mutations with observable local commands, and
    # redirect the vhost probe to the isolated HTTP fixture. Real TLS/Nginx is
    # covered separately by test_artifact_http.py.
    for task in tasks[1]["block"]:
        if "ansible.builtin.systemd_service" in task or task["name"].startswith("Validate nginx"):
            unit = task.pop("ansible.builtin.systemd_service", {})
            task.pop("ansible.builtin.command", None)
            label = "service:" + unit["name"] if unit else "nginx:validate"
            task["ansible.builtin.command"] = {
                "argv": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; "
                    f"assert Path({str(current)!r}).resolve() == Path({str(previous)!r}); "
                    f"f = Path({str(events)!r}).open('a'); f.write(sys.argv[1] + '\\n'); f.close()",
                    label,
                ]
            }
        if "until" in task:
            task.update(
                retries=2, delay=0
            )  # Keep failure tests fast; production bounds asserted above.
        if task["name"] == "Verify previous Registry v1 release after rollback":
            task["ansible.builtin.uri"]["url"] = (
                f"http://127.0.0.1:{backend.server_port}/index.json"
            )

    play = [
        {
            "hosts": "all",
            "connection": "local",
            "gather_facts": False,
            "vars": {
                "packages_registry_previous_release_path": str(previous),
                "packages_registry_current_path": str(current),
                "packages_registry_backend_port": backend.server_port,
                "packages_registry_frontend_port": frontend.server_port,
                "packages_registry_manage_nginx": True,
                "packages_registry_domain": "localhost",
            },
            "tasks": [
                {
                    "block": [{"ansible.builtin.fail": {"msg": "original deployment failure"}}],
                    "rescue": tasks,
                }
            ],
        }
    ]
    play_path = tmp_path / "rollback.yml"
    play_path.write_text(yaml.safe_dump(play))
    try:
        result = subprocess.run(
            [ansible, "-i", "localhost,", str(play_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=45,
        )
        output = result.stdout + result.stderr
        assert result.returncode != 0  # The original deployment must still be reported as failed.
        assert "original deployment failure" in output
        assert current.resolve() == previous
        recorded = events.read_text().splitlines()
        assert recorded[:2] == [
            "service:packages-registry-backend.service",
            "service:packages-registry-frontend.service",
        ]
        assert counts["backend"] >= 2
        assert counts["frontend"] >= 1
        if unhealthy:
            assert "Rollback also failed" in output
            assert "Require healthy package explorer processes after rollback" in output
            assert counts[unhealthy] == 3
            assert "nginx:validate" not in recorded
            assert "service:nginx" not in recorded
            assert "backend:/index.json" not in recorded
        else:
            assert f"Rollback to {previous} succeeded." in output
            assert "Rollback also failed" not in output
            assert recorded[-3:] == ["nginx:validate", "service:nginx", "backend:/index.json"]
            assert recorded.index("frontend:/") < recorded.index("nginx:validate")
    finally:
        for server in (backend, frontend):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
