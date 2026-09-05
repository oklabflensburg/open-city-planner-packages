"""Build in two separate orchestrator processes and compare artifacts and components."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.compare_ocp import compare


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--host-root", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ocp-cross-run-") as temporary:
        outputs = []
        for index in range(2):
            root = Path(temporary) / str(index)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.ocp_builder",
                    "--module",
                    args.module,
                    "--tag",
                    args.tag,
                    "--host-root",
                    str(args.host_root.resolve()),
                    "--output",
                    str(root),
                ],
                check=True,
                umask=(0o002, 0o077)[index],
            )
            outputs.append(next((root / "candidate").glob("*.ocp")))
        report = compare(outputs[0].read_bytes(), outputs[1].read_bytes())
        print(json.dumps(report, indent=2))
        if not report["identical"]:
            raise SystemExit("cross-run artifact mismatch")


if __name__ == "__main__":
    main()
