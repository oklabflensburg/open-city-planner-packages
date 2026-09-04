from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/registry.yml"
BUILDER_WORKFLOW_PATH = ROOT / ".github/workflows/ocp-builder.yml"


def workflow_source() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def workflow() -> dict:
    return yaml.load(workflow_source(), Loader=yaml.BaseLoader)


def builder_workflow() -> dict:
    return yaml.load(
        BUILDER_WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )


def test_central_builder_is_manual_allowlisted_and_has_no_commit_override() -> None:
    value = builder_workflow()
    assert set(value["on"]) == {"workflow_dispatch"}
    inputs = value["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"module_id", "source_tag", "planned_channel"}
    assert inputs["module_id"]["options"] == ["statistics", "analysis-areas"]
    assert inputs["planned_channel"]["default"] == "beta"
    source = BUILDER_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "source_commit:" not in source
    assert "artifact_url:" not in source
    assert "auto-merge" not in source


def test_untrusted_builder_job_has_read_only_permissions_and_no_secrets() -> None:
    value = builder_workflow()
    build = value["jobs"]["build"]
    assert value["permissions"] == {"contents": "read"}
    assert build["permissions"] == {"contents": "read"}
    build_source = yaml.safe_dump(build)
    assert "secrets." not in build_source
    assert value["jobs"]["prepare-review"]["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
    }


def test_builder_actions_are_pinned_and_no_auto_merge_exists() -> None:
    source = BUILDER_WORKFLOW_PATH.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*uses:\s*([^\s#]+)", source, flags=re.MULTILINE)
    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in uses)
    assert "gh pr merge" not in source


def test_registry_triggers_remain_pr_and_main_push_only() -> None:
    triggers = workflow()["on"]
    assert set(triggers) == {"pull_request", "push"}
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request_target" not in workflow_source()


def test_production_deploy_runs_only_after_successful_main_ci() -> None:
    deploy = workflow()["jobs"]["deploy-production"]
    assert deploy["if"] == (
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )
    assert set(deploy["needs"]) == {"validate", "ansible", "web"}
    assert deploy["environment"] == {"name": "production"}
    assert deploy["permissions"] == {"contents": "read"}
    assert deploy["concurrency"] == {
        "group": "packages-registry-production",
        "cancel-in-progress": "false",
    }


def test_production_checkout_and_ansible_use_exact_push_sha() -> None:
    deploy = workflow()["jobs"]["deploy-production"]
    checkout = deploy["steps"][0]
    assert checkout["with"] == {
        "ref": "${{ github.sha }}",
        "persist-credentials": "false",
    }
    deploy_step = next(
        step
        for step in deploy["steps"]
        if step["name"] == "Deploy exact reviewed commit with existing Ansible safety gates"
    )
    command = deploy_step["run"]
    assert "playbooks/deploy.yml" in command
    assert '-e "packages_registry_deploy_ref=${GITHUB_SHA}"' in command
    assert "publish-artifact.yml" not in command
    for forbidden_ref in ("=main", "origin/main", "=HEAD", "=latest"):
        assert forbidden_ref not in command


def test_production_ssh_uses_environment_inputs_and_pinned_trust() -> None:
    source = workflow_source()
    deploy = workflow()["jobs"]["deploy-production"]
    assert deploy["env"] == {
        "PACKAGES_REGISTRY_HOST": "${{ vars.PACKAGES_REGISTRY_HOST }}",
        "PACKAGES_REGISTRY_REMOTE_USER": "${{ vars.PACKAGES_REGISTRY_REMOTE_USER }}",
    }
    assert "${{ secrets.PACKAGES_REGISTRY_SSH_PRIVATE_KEY }}" in source
    assert "${{ secrets.PACKAGES_REGISTRY_SSH_KNOWN_HOSTS }}" in source
    assert 'chmod 600 "${HOME}/.ssh/id_ed25519"' in source
    assert 'chmod 600 "${HOME}/.ssh/known_hosts"' in source
    assert "StrictHostKeyChecking=yes" in source
    assert "StrictHostKeyChecking=no" not in source
    assert "ANSIBLE_HOST_KEY_CHECKING" not in source
    assert "ssh-keyscan" not in source
    assert "set -x" not in source
    assert "printenv" not in source
    assert "cat ~/.ssh/id_ed25519" not in source


def test_inventory_is_generated_at_runtime_and_ignored() -> None:
    source = workflow_source()
    assert "deploy/ansible/inventory/production.ini" in source
    assert "[packages_registry]" in source
    assert "ansible_python_interpreter=/usr/bin/python3" in source
    assert "deploy/ansible/inventory/production.ini" in (ROOT / ".gitignore").read_text(
        encoding="utf-8"
    )
    inspected_roots = (ROOT / ".github", ROOT / "deploy", ROOT / "scripts", ROOT / "tests")
    assert not any(
        path.name in {"id_ed25519", "id_rsa"}
        for inspected_root in inspected_roots
        for path in inspected_root.rglob("*")
        if path.is_file()
    )


def test_all_workflow_actions_remain_pinned_to_full_commit_sha() -> None:
    uses = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow_source(), flags=re.MULTILINE)
    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in uses)


def test_web_job_runs_locked_frontend_quality_gates() -> None:
    web = workflow()["jobs"]["web"]
    assert web["timeout-minutes"] == "15"
    steps = {step["name"]: step for step in web["steps"]}
    assert steps["Set up pinned Node.js"]["with"]["node-version"] == "22.22.3"
    assert steps["Set up pinned pnpm"]["with"]["version"] == "11.22.0"
    assert steps["Install locked frontend dependencies"]["run"] == (
        "pnpm install --frozen-lockfile"
    )
    assert steps["Type-check package explorer"]["run"] == "pnpm typecheck"
    assert steps["Test package explorer"]["run"] == "pnpm test"
    assert steps["Build package explorer SSR application"]["run"] == "pnpm build"


def test_main_pushes_are_not_cancelled_and_production_deploys_serialize() -> None:
    concurrency = workflow()["concurrency"]
    assert "github.run_id" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )
