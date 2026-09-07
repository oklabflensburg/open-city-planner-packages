"""Run real browser auth against an explicitly disposable DB, never a deployment."""

import os
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from web.backend.app.registry_import_v1 import import_registry

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    raw = os.environ.get("PACKAGES_REGISTRY_TEST_DATABASE_URL")
    if not raw:
        raise SystemExit(
            "Set PACKAGES_REGISTRY_TEST_DATABASE_URL to a disposable PostgreSQL database"
        )
    database = f"auth_e2e_{uuid4().hex}"
    admin = create_engine(raw, hide_parameters=True, isolation_level="AUTOCOMMIT")
    backend_port, frontend_port = free_port(), free_port()
    origin = f"http://localhost:{frontend_port}"
    processes = []
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    try:
        engine = create_engine(admin.url.set(database=database), hide_parameters=True)
        with engine.begin() as connection:
            config = Config(str(ROOT / "web/backend/auth_alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            registry_config = Config(str(ROOT / "web/backend/alembic.ini"))
            registry_config.attributes["connection"] = connection
            command.upgrade(registry_config, "head")
        import_registry(engine, ROOT / "registry")
        url = engine.url.render_as_string(hide_password=False)
        auth_url = engine.url.set(drivername="postgresql+asyncpg").render_as_string(
            hide_password=False
        )
        engine.dispose()
        env = dict(
            os.environ,
            AUTH_ENABLED="true",
            AUTH_DATABASE_URL=auth_url,
            PACKAGES_REGISTRY_DATABASE_URL=url,
            PACKAGES_REGISTRY_V2_API_ENABLED="true",
            APP_ENVIRONMENT="development",
            EMAIL_BACKEND="console",
            APP_BASE_URL=origin,
            CORS_ORIGINS=origin,
            WEBAUTHN_ORIGIN=origin,
            WEBAUTHN_RP_ID="localhost",
            NUXT_PUBLIC_AUTH_ENABLED="true",
            NUXT_PUBLIC_SITE_URL=origin,
            NUXT_API_BASE_INTERNAL=f"http://127.0.0.1:{backend_port}/api",
            HOST="127.0.0.1",
            PORT=str(frontend_port),
            AUTH_E2E_BASE_URL=origin,
        )
        processes.append(
            subprocess.Popen(
                [
                    str(ROOT / ".venv/bin/python"),
                    "-m",
                    "uvicorn",
                    "web.backend.app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(backend_port),
                    "--no-access-log",
                ],
                cwd=ROOT,
                env=env,
            )
        )
        processes.append(
            subprocess.Popen(
                ["node", ".output/server/index.mjs"], cwd=ROOT / "web/frontend", env=env
            )
        )
        for url in [f"http://127.0.0.1:{backend_port}/health/auth", f"{origin}/anmelden"]:
            for _ in range(100):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("Local auth test service exited")
                try:
                    if httpx.get(url, timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Local auth test service did not become ready")
        result = subprocess.run(
            ["pnpm", "exec", "playwright", "test"], cwd=ROOT / "web/frontend", env=env
        )
        return result.returncode
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        admin.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
