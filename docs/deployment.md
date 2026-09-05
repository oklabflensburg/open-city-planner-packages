# Registry and application deployment contract

The package registry is a static, deterministically built release artifact tree.
Ansible deploys an explicit Git ref as an immutable commit SHA, validates the
resulting `dist/`, and switches one atomic `current` symlink. Nginx serves JSON
from `current/dist` and immutable `.ocp` bytes from a separate persistent store.
FastAPI and Nuxt SSR run as unprivileged systemd services from the same release;
Nginx proxies `/api/` to FastAPI and other application routes to Nuxt.

This describes current operations. The [Registry Service v2 ADR](adr/registry-service-v2.md)
defines the future separation of module publication from application deployment.

The complete operator runbook, variables, bootstrap, TLS workflow, rollback,
retention, permissions, and troubleshooting commands live in
[`deploy/ansible/README.md`](../deploy/ansible/README.md). The short production
sequence is:

1. Pull requests run Registry, Ansible, and artifact-verification gates without
   access to the Production Environment.
2. Bootstrap the target once with `playbooks/bootstrap.yml`.
3. Point DNS at the host and issue TLS separately with the opt-in
   `playbooks/certificates.yml`.
4. After merge, the successful `main` push runs validation and Ansible tests,
   then the protected Production job invokes `playbooks/deploy.yml` with
   `packages_registry_deploy_ref=${GITHUB_SHA}`.
5. Ansible updates the non-forced checkout and resolves the actual commit SHA.
6. It materializes `releases/<sha>` using `git archive`, runs locked dependency
   sync, lint, tests, source validation, and deterministic `dist/` build.
7. Disk space, committed output, whitespace, and `dist/index.json` are checked
   before `.release-ready` is written.
8. TLS and Nginx syntax are checked before activation.
9. `current` switches to the ready release; local and external HTTPS smoke checks
   require HTTP 200, JSON, and Registry schema version 1.
10. A failure restores and verifies the previous release, while success prunes
    old inactive releases by mtime.

The target layout is:

```text
/opt/open-city-planner-packages/
├── repo/
├── releases/<commit-sha>/
├── current -> /opt/open-city-planner-packages/releases/<commit-sha>
└── artifacts/modules/<module-id>/<version>/<module-id>-<version>.ocp
```

Index and module metadata come from
`/opt/open-city-planner-packages/current/dist` with `application/json` and
`Cache-Control: public, max-age=300`. Canonical `.ocp` routes map to the
separate artifact tree with `application/octet-stream`, one-year immutable
cache headers, and `nosniff`. The JSON and artifact routes remain separate from
the API/UI proxies; the vhost has no wildcard CORS, source-tree exposure or
directory listing.

The normal deploy also builds the Nuxt frontend, restarts the API/SSR services
and automatically mirrors missing reviewed artifacts through
`scripts/publish_artifacts.py` before activation, then verifies their public bytes
and headers. `playbooks/publish-artifact.yml` remains a separate recovery tool.
Release rollback and retention inspect only `releases/` and cannot delete
`artifacts/`. Artifact verification remains a pull-request publishing gate, and
registry availability is never a runtime dependency for installed modules.
