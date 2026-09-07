#!/usr/bin/env python3
"""Build private, ephemeral Ansible auth inputs; never print secret values."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "roles/packages_registry/filter_plugins"
sys.path.insert(0, str(PLUGIN_DIR))
from auth_runtime import FIELDS, auth_extra_vars  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    flag = os.environ.get("PACKAGES_REGISTRY_AUTH_ENABLED", "").strip().lower()
    if flag not in ("", "false", "true"):
        raise SystemExit("PACKAGES_REGISTRY_AUTH_ENABLED must be true or false")
    enabled = flag == "true"
    try:
        values = auth_extra_vars(
            {
                f"packages_auth_{field}": os.environ.get(f"PACKAGES_AUTH_{field.upper()}", "")
                for field in FIELDS
            }
            if enabled
            else {},
            enabled,
        )
    except ValueError as exc:
        # Contract errors contain only allowlisted names, never input values.
        raise SystemExit(str(exc)) from None
    values["packages_registry_auth_enabled"] = enabled
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=args.output.parent,
            prefix=args.output.name + ".",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            json.dump(values, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
