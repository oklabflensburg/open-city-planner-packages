"""Compare OCP bytes and nested ZIP/wheel and gzip/tar payloads without extraction."""

import argparse
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory(data: bytes, kind: str) -> dict:
    if kind == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {
                entry.filename: (
                    archive.read(entry),
                    {
                        key: getattr(entry, key)
                        for key in (
                            "date_time",
                            "external_attr",
                            "create_system",
                            "compress_type",
                            "compress_size",
                            "flag_bits",
                            "create_version",
                            "extract_version",
                        )
                    }
                    | {"extra": entry.extra.hex(), "comment": entry.comment.hex()},
                )
                for entry in archive.infolist()
            }
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return {
            entry.name: (
                archive.extractfile(entry).read() if entry.isfile() else b"",
                {
                    key: getattr(entry, key)
                    for key in (
                        "mode",
                        "uid",
                        "gid",
                        "uname",
                        "gname",
                        "mtime",
                        "linkname",
                        "pax_headers",
                    )
                },
            )
            for entry in archive
        }


def compare(a: bytes, b: bytes, kind: str = "zip") -> dict:
    left, right = inventory(a, kind), inventory(b, kind)
    report = {
        "sha256": [digest(a), digest(b)],
        "identical": a == b,
        "only_left": sorted(left.keys() - right.keys()),
        "only_right": sorted(right.keys() - left.keys()),
        "same_entry_order": list(left) == list(right),
        "entries": {},
    }
    if kind == "tar":
        report["gzip_headers"] = [a[:10].hex(), b[:10].hex()]
    for name in sorted(left.keys() & right.keys()):
        aa, am = left[name]
        bb, bm = right[name]
        entry = {
            "content_identical": aa == bb,
            "sha256": [digest(aa), digest(bb)],
            "metadata_differences": {k: [am[k], bm[k]] for k in am if am[k] != bm[k]},
        }
        if name.endswith((".whl", ".ocp", ".tgz")):
            entry["nested"] = compare(aa, bb, "tar" if name.endswith(".tgz") else "zip")
        if name.endswith((".yaml", ".json", "METADATA", "WHEEL")) and aa != bb:
            entry["text"] = [aa.decode("utf-8", "replace"), bb.decode("utf-8", "replace")]
        report["entries"][name] = entry
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.left.read_bytes(), args.right.read_bytes()), indent=2))


if __name__ == "__main__":
    main()
