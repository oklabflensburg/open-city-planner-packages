"""Import validated Registry v1 into an explicitly selected shadow PostgreSQL DB."""

import argparse
import json
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from scripts.registry import build_index, canonical_json, canonical_module, load_registry
from web.backend.app.db.config import database_engine
from web.backend.app.db.models import Module, ModuleChannel, Publisher
from web.backend.app.db.repository import RegistryConflict, RegistryDatabaseRepository


def import_registry(engine: Engine, registry_root: Path) -> dict:
    modules = load_registry(registry_root)
    expected = [canonical_module(module) for module in modules]
    channels = {entry["id"]: entry["channels"] for entry in build_index(modules)["modules"]}
    with Session(engine) as session, session.begin():
        # Serialize shadow imports only; this is not a promotion authorization mechanism.
        session.execute(text("SELECT pg_advisory_xact_lock(450044)"))
        repo = RegistryDatabaseRepository(session)
        for module in modules:
            publisher = module["publisher"]
            repo.ensure_record(Publisher, {"id": publisher["id"]}, name=publisher["name"])
        for module in modules:
            repo.ensure_record(
                Module,
                {"id": module["id"]},
                **{
                    name: module.get(name)
                    for name in (
                        "name",
                        "description",
                        "classification",
                        "license",
                        "source_repository",
                        "homepage",
                        "documentation_url",
                    )
                },
                publisher_id=module["publisher"]["id"],
            )
        inserted = sum(
            repo.insert_published_version(module["id"], release, historical_order=position)
            for module in expected
            for position, release in enumerate(module["versions"])
        )
        for module_id, targets in channels.items():
            for channel, target in targets.items():
                repo.ensure_record(
                    ModuleChannel,
                    {"module_id": module_id, "channel": channel},
                    version=target["version"],
                )
        if canonical_json(repo.project_v1()) != canonical_json(expected):
            raise RegistryConflict("DB projection differs from complete Registry v1 source")
        if repo.channel_targets() != channels:
            raise RegistryConflict("DB channel pointers differ from Registry v1 index")
        report = {
            "inserted_versions": inserted,
            "counts": repo.counts(),
            "channels": channels,
            "v1_parity": True,
            "mode": "shadow",
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-root", type=Path, default=Path("registry"))
    parser.add_argument(
        "--confirm-shadow-import",
        action="store_true",
        required=True,
        help="Confirm the configured database is disposable shadow infrastructure",
    )
    args = parser.parse_args()
    engine = None
    try:
        engine = database_engine()
        print(json.dumps(import_registry(engine, args.registry_root), indent=2, sort_keys=True))
    except SQLAlchemyError:
        # Driver diagnostics can include connection credentials/parameters. Do not print them.
        print("Shadow import failed: database operation rejected; transaction rolled back.")
        return 1
    except (OSError, ValueError) as exc:
        print(f"Shadow import failed: {exc}")
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
