"""Run with the pinned Host's Python, using its real client, bundle and installer helpers.

No network: metadata is the DB HTTP output captured by the parent integration test;
only the synthetic fixture's artifact bytes are available to the mock transport.
"""

import json
import sys
from pathlib import Path

import httpx
from app.platform.modules.installer import read_modules_lock
from app.platform.modules.registry import ModuleRegistryClient, ModuleRegistryIntegrityError

from tests.test_module_bundle import _bundle
from tests.test_module_registry import _documents, _install_from_client

root = Path(sys.argv[2])
if sys.argv[1] == "prepare":
    root.mkdir(parents=True, exist_ok=True)
    bundle, _ = _bundle(root, "registry-module", backend=False, frontend=True)
    module = json.loads(_documents(bundle)["/modules/registry-module.json"])
    # Host fixture uses github.com/example; the Registry correctly classifies it as community.
    module["classification"] = "reviewed-community"
    module["versions"][0]["artifact"]["url"] = (
        "https://packages.stadtplaner.oklabflensburg.de/"
        "modules/registry-module/1.0.0/registry-module-1.0.0.ocp"
    )
    source = root / "source"
    (source / "modules").mkdir(parents=True)
    (source / "registry.json").write_text('{"schema_version":1}')
    (source / "modules/registry-module.json").write_text(json.dumps(module))
    raise SystemExit(0)

snapshot = root / "snapshot"
requests = []


def transport(request):
    requests.append(request.url.path)
    path = snapshot / request.url.path.lstrip("/")
    if path.is_file():
        return httpx.Response(200, content=path.read_bytes(), headers={"Cache-Control": "no-cache"})
    if request.url.path == "/modules/registry-module/1.0.0/registry-module-1.0.0.ocp":
        return httpx.Response(200, content=(root / "registry-module-1.0.0.ocp").read_bytes())
    return httpx.Response(404)


with ModuleRegistryClient(transport=httpx.MockTransport(transport)) as client:
    index = json.loads((snapshot / "index.json").read_bytes())
    for entry in index["modules"]:
        metadata = json.loads((snapshot / entry["metadata"].lstrip("/")).read_bytes())
        for channel, pointer in entry["channels"].items():
            selected = client.resolve(entry["id"], channel=channel)
            assert selected.version == pointer["version"]
            assert selected.sha256 == pointer["sha256"]
        for version in metadata["versions"]:
            selected = client.resolve(
                entry["id"],
                version=version["version"],
                expected_sha256=version["artifact"]["sha256"],
            )
            assert selected.requirements.model_dump() == version["requires"]
            assert selected.channel == version["channel"]
            assert selected.artifact_url == version["artifact"]["url"]
            assert selected.source_tag == version.get("source_tag")
            assert selected.source_commit == version["source_commit"]
            try:
                client.resolve(entry["id"], version=version["version"], expected_sha256="0" * 64)
            except ModuleRegistryIntegrityError:
                pass
            else:
                raise AssertionError("Host accepted an incorrect deployment digest")
        assert entry["metadata"] in requests
    assert "/index.json" in requests
    if sys.argv[1] == "install":
        release, installed, installer = _install_from_client(client, root / "state")
        assert not installed.enabled
        assert installed.artifact.sha256 == release.sha256
        assert read_modules_lock(installer.lock_path).modules == (installed,)
        _, repeated, _ = _install_from_client(client, root / "state", version="1.0.0")
        assert repeated == installed
        installer.enable("registry-module")  # Real host/sdk/dependency preflight.
        installer.disable("registry-module")
print("Pinned Host DB snapshot: selection, metadata, digests and requirements passed")
