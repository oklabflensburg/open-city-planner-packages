"""Read-only parity preflight over one DB snapshot and a frozen v1 dist directory."""

import argparse
import json
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from scripts.registry import canonical_json
from web.backend.app.api.registry_compatibility import validate_v1_representability
from web.backend.app.api.registry_v2 import EXPECTED_SCHEMA_REVISION, read_repository
from web.backend.app.db.config import database_engine


def verify(engine, dist: Path) -> dict:
    with read_repository(engine) as repository:
        if repository.schema_revision() != EXPECTED_SCHEMA_REVISION:
            raise ValueError("Registry database schema is not ready")
        modules = repository.project_v1()
        index = validate_v1_representability(modules, repository.channel_targets())
        documents = {"index.json": index, **{f"modules/{m['id']}.json": m for m in modules}}
        if {p.name for p in (dist / "modules").glob("*.json")} != {
            f"{m['id']}.json" for m in modules
        }:
            raise ValueError("Module file set differs from DB projection")
        for name, document in documents.items():
            if (dist / name).read_bytes() != canonical_json(document).encode("utf-8"):
                raise ValueError(f"Byte parity failed: {name}")
        return {
            "index_byte_parity": True,
            "module_byte_parity": len(modules),
            "published_versions": sum(len(m["versions"]) for m in modules),
            "representable": True,
            "schema_revision": EXPECTED_SCHEMA_REVISION,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True, help="Frozen reviewed dist directory")
    args = parser.parse_args()
    engine = None
    try:
        engine = database_engine()
        print(json.dumps(verify(engine, args.dist), sort_keys=True))
    except SQLAlchemyError:
        print("Registry v1 verification failed: database unavailable")
        return 1
    except (OSError, ValueError):
        print("Registry v1 verification failed: schema, channels or frozen bytes differ")
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
