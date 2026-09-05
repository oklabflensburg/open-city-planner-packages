"""Serve an isolated temp Artifact Store with the actual production Nginx template."""

import hashlib
import shutil
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from scripts.artifact_store import FilesystemArtifactStore

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "roles/packages_registry/templates/packages-registry.nginx.conf.j2"
)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_real_nginx_serves_only_complete_immutable_artifacts(tmp_path):
    nginx = shutil.which("nginx")
    assert nginx, "Install nginx for the explicit Ansible/HTTP integration suite"
    openssl = shutil.which("openssl")
    assert openssl
    source = tmp_path / "reviewed.ocp"
    source.write_bytes(b"complete reviewed fixture")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    record = store.publish("statistics", "0.4.0", source, digest).artifact
    # Partial/source files must never be exposed by the template.
    (store.root / ".staging/secret.partial").write_bytes(b"not public")
    target = store.root / record.storage_locator
    (target.parent / ".statistics-0.4.0.ocp.partial").write_bytes(b"not public")
    cert, key = tmp_path / "certificate.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    http_port, https_port = free_port(), free_port()
    rendered = (
        Environment(undefined=StrictUndefined)
        .from_string(TEMPLATE.read_text())
        .render(
            packages_registry_domain="localhost",
            packages_registry_acme_webroot=str(tmp_path / "acme"),
            packages_registry_certificate_name="localhost",
            packages_registry_current_path=str(tmp_path / "current"),
            packages_registry_artifact_root=str(store.root),
            packages_registry_backend_port=free_port(),
            packages_registry_frontend_port=free_port(),
        )
    )
    rendered = (
        rendered.replace("listen 80;", f"listen 127.0.0.1:{http_port};")
        .replace("listen [::]:80;", "")
        .replace("listen 443 ssl;", f"listen 127.0.0.1:{https_port} ssl;")
        .replace("listen [::]:443 ssl;", "")
        .replace("/etc/letsencrypt/live/localhost/fullchain.pem", str(cert))
        .replace("/etc/letsencrypt/live/localhost/privkey.pem", str(key))
        .replace("/var/log/nginx/packages-registry-access.log", str(tmp_path / "access.log"))
        .replace("/var/log/nginx/packages-registry-error.log", str(tmp_path / "error.log"))
    )
    config = tmp_path / "nginx.conf"
    config.write_text(
        f"pid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/master.log;\n"
        f"events {{}}\nhttp {{ access_log off; client_body_temp_path {tmp_path}/client; "
        f"proxy_temp_path {tmp_path}/proxy; fastcgi_temp_path {tmp_path}/fastcgi; "
        f"uwsgi_temp_path {tmp_path}/uwsgi; scgi_temp_path {tmp_path}/scgi; {rendered} }}\n"
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # This test's generated certificate, loopback only.

    def get(path):
        try:
            with urllib.request.urlopen(
                f"https://127.0.0.1:{https_port}{path}", context=context, timeout=2
            ) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    command = [nginx, "-p", str(tmp_path), "-c", str(config)]
    subprocess.run([*command, "-t"], check=True, capture_output=True)
    process = subprocess.Popen(
        [*command, "-g", "daemon off;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                status, headers, body = get("/" + record.storage_locator)
                break
            except urllib.error.URLError:
                if time.monotonic() >= deadline or process.poll() is not None:
                    raise
                time.sleep(0.02)
        assert status == 200
        assert body == source.read_bytes()
        assert headers.get_content_type() == "application/octet-stream"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cache-Control"] == "public, max-age=31536000, immutable"
        assert int(headers["Content-Length"]) == len(body)
        for path in (
            "/.staging/secret.partial",
            "/modules/statistics/0.4.0/",
            "/modules/statistics/0.4.0/.statistics-0.4.0.ocp.partial",
            "/registry/modules/statistics.json",
        ):
            assert get(path)[0] != 200
        # Never follow a final symlink, even to otherwise readable matching bytes.
        target.unlink()
        target.symlink_to(source)
        assert get("/" + record.storage_locator)[0] in {403, 404}
    finally:
        process.terminate()
        process.wait(timeout=5)
