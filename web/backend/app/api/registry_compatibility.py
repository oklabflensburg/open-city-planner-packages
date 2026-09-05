"""Read-only Registry v1 boundary over the shared historical DB projection."""

from scripts.registry import build_index, validate_module, validate_module_id
from web.backend.app.api.registry_queries import NotFound
from web.backend.app.db.repository import RegistryDatabaseRepository


class V1RepresentabilityError(ValueError):
    """Current pointers cannot be expressed by unchanged v1 clients."""


def validate_v1_representability(modules, channel_targets) -> dict:
    """Reusable preflight for #49: exact channel sets, versions AND digests must agree.

    build_index is the original v1 selection oracle (including SemVer tie behavior).
    Historical labels are immutable; rollback/relabeling cannot override this rule.
    """
    for module in modules:
        validate_module(module, "Registry v1 DB projection")
    index = build_index(modules)
    expected = {entry["id"]: entry["channels"] for entry in index["modules"]}
    if expected != channel_targets:
        raise V1RepresentabilityError("Current channels are not representable in Registry v1")
    # Explicit DB authority, only after proving equivalence to v1 client selection.
    for entry in index["modules"]:
        entry["channels"] = channel_targets[entry["id"]]
    return index


class RegistryCompatibilityService:
    def __init__(self, repository: RegistryDatabaseRepository):
        self.repository = repository

    def index(self):
        modules = self.repository.project_v1()
        return validate_v1_representability(modules, self.repository.channel_targets())

    def module(self, module_id: str):
        validate_module_id(module_id)
        modules = self.repository.project_v1(module_id)
        if not modules:
            raise NotFound("Published module not found")
        validate_v1_representability(modules, self.repository.channel_targets([module_id]))
        return modules[0]
