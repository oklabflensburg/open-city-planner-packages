# Static registry deployment contract

The package registry is a static, deterministically built release artifact tree.
Ansible deploys an explicit Git ref as an immutable commit SHA, validates the
resulting `dist/`, and switches one atomic `current` symlink. Nginx serves JSON
from `current/dist` and immutable `.ocp` bytes from a separate persistent store.
No application runtime participates in deployment or serving.

The complete operator runbook, variables, bootstrap, TLS workflow, rollback,
retention, permissions, and troubleshooting commands live in
[`deploy/ansible/README.md`](../deploy/ansible/README.md). The short production
sequence is:

1. Require successful Registry CI for the intended `main` commit.
2. Bootstrap the target once with `playbooks/bootstrap.yml`.
3. Point DNS at the host and issue TLS separately with the opt-in
   `playbooks/certificates.yml`.
4. Run `playbooks/deploy.yml` with
   `packages_registry_deploy_ref=<40-character-commit-sha>`.
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
cache headers, and `nosniff`. The vhost has no proxy, SPA fallback, wildcard
CORS, source-tree exposure, or directory listing.

The normal deploy still publishes Registry code and JSON only. Artifact
publication is the separate explicit `playbooks/publish-artifact.yml` operation;
release rollback and retention inspect only `releases/` and cannot delete
`artifacts/`. Artifact verification remains a pull-request publishing gate, and
registry availability is never a runtime dependency for installed modules.
