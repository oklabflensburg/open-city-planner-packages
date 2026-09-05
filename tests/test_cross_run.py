import io
import json
import os
import sys
import zipfile

import pytest

from scripts.compare_ocp import compare
from scripts.ocp_builder import BuilderError, check_candidate_history, run
from tests.test_ocp_builder import candidate, identity


def wheel(mode):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        entry = zipfile.ZipInfo("package/module.py", (1980, 1, 1, 0, 0, 0))
        entry.external_attr = mode << 16
        archive.writestr(entry, b"identical source")
    return stream.getvalue()


def test_compare_reports_wheel_mode_drift_without_content_drift():
    diff = compare(wheel(0o100664), wheel(0o100644))
    assert not diff["identical"]
    entry = diff["entries"]["package/module.py"]
    assert entry["content_identical"]
    assert entry["metadata_differences"] == {
        "external_attr": [0o100664 << 16, 0o100644 << 16],
    }


def test_separate_processes_ignore_inherited_umask(tmp_path):
    previous = os.umask(0o002)
    try:
        a = run([sys.executable, "-c", "import os; print(oct(os.umask(0)))"])
        os.umask(0o077)
        b = run([sys.executable, "-c", "import os; print(oct(os.umask(0)))"])
    finally:
        os.umask(previous)
    assert a == b == "0o22"


@pytest.mark.parametrize("remote", [False, True])
def test_previous_candidate_digest_is_immutable(tmp_path, monkeypatch, remote):
    data = candidate()
    path = tmp_path / "candidates/statistics/0.4.0/provenance.json"
    monkeypatch.setattr("scripts.ocp_builder.ROOT", tmp_path)
    if not remote:
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data))

    def git(command, **kwargs):
        if not remote:
            return ""
        if command[1] == "ls-remote":
            return "a" * 40 + "\trefs/heads/main"
        if command[1] == "ls-tree":
            return "candidates/statistics/0.4.0/provenance.json"
        if command[1] == "show":
            return json.dumps(data)
        return ""

    monkeypatch.setattr("scripts.ocp_builder.run", git)
    check_candidate_history(identity(), "c" * 64, 1)
    with pytest.raises(BuilderError, match="existing candidate"):
        check_candidate_history(identity(), "d" * 64, 1)
