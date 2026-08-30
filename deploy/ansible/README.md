# Ansible deployment for the static package registry

This directory deploys one immutable Git commit as a validated static release
and provides a separate explicit operation for immutable `.ocp` publication.
Nginx serves Registry JSON from `/opt/open-city-planner-packages/current/dist`
and canonical bundle URLs from the persistent `artifacts/` tree. There is no
registry application process, systemd application service, database, or runtime
environment file.

## Prerequisites and inventory

The controller needs Python and the locked project environment (`uv sync
--frozen`). The target is a Debian/Ubuntu host reachable through SSH with
`become` access. SSH host-key checking remains enabled.

Copy `inventory/production.example.ini` to an untracked operator inventory such
as `inventory/production.ini`, replace the example hostname, and configure the
SSH login through `~/.ssh/config` or `ANSIBLE_REMOTE_USER`. Do not commit host
credentials or production secrets. The dedicated inventory group is
`packages_registry`.

Commands below run from `deploy/ansible`:

```bash
uv sync --frozen
export ANSIBLE_REMOTE_USER=DEPLOY_USER
ansible -i inventory/production.ini packages_registry -m ping
```

## First deployment: bootstrap, TLS, deploy

Bootstrap installs only Git, Python/venv, Nginx, CA certificates, Certbot, the
unprivileged `ocp-packages` account, deployment directories, and uv 0.12.5 in a
root-owned tooling venv. It does not install Node.js or an application runtime.

```bash
uv run ansible-playbook -i inventory/production.ini playbooks/bootstrap.yml
```

DNS for `packages.stadtplaner.oklabflensburg.de` must already point at the host.
Certificate issuance is separate and explicitly opt-in:

```bash
uv run ansible-playbook -i inventory/production.ini playbooks/certificates.yml \
  -e packages_registry_manage_certificates=true \
  -e packages_registry_certbot_email=ADMIN@example.org
```

The certificate playbook uses an isolated webroot challenge and skips issuance
when the named certificate already exists. A normal deploy never requests or
renews a certificate. It fails before changing the vhost unless both Let's
Encrypt certificate files exist.

The Registry workflow deploys automatically after validation and Ansible tests
succeed on a push to `main`. The Production job checks out and passes the exact
`${{ github.sha }}` to this playbook; it never deploys the moving branch name.

For an authorized manual recovery, deploy an explicit commit SHA after Registry
CI has passed:

```bash
uv run ansible-playbook -i inventory/production.ini playbooks/deploy.yml \
  -e packages_registry_deploy_ref=<40-character-commit-sha>
```

`main` is the convenience default, but production should use an immutable SHA.
The checkout uses `force: false`; dirty server-side changes therefore stop an
update rather than being silently discarded. Ansible resolves the selected ref
to the actual 40-character commit and uses only that SHA as release identity.

## GitHub Production environment

The `deploy-production` job runs only when both conditions are true:

```text
github.event_name == push
github.ref == refs/heads/main
```

It needs the successful `validate` and `ansible` jobs, uses job-level
`contents: read`, and serializes deployments through the non-cancelling
`packages-registry-production` concurrency group. Pull-request jobs do not
reference the Environment and cannot receive its credentials.

Create a GitHub Environment named `production` with these Environment secrets:

```text
PACKAGES_REGISTRY_SSH_PRIVATE_KEY
PACKAGES_REGISTRY_SSH_KNOWN_HOSTS
```

`PACKAGES_REGISTRY_SSH_KNOWN_HOSTS` must contain the independently verified
Production host key entry. It is the trust root; the workflow never uses
`ssh-keyscan` and never disables strict host-key checking.

Configure these Environment variables:

```text
PACKAGES_REGISTRY_HOST
PACKAGES_REGISTRY_REMOTE_USER
```

The runner writes the private key to `~/.ssh/id_ed25519` and the pinned entries
to `~/.ssh/known_hosts`, both mode `0600`, without printing either value. It
generates the ignored `inventory/production.ini` at runtime, checks SSH in
batch mode with `StrictHostKeyChecking=yes`, and calls:

```bash
uv run ansible-playbook \
  -i inventory/production.ini \
  playbooks/deploy.yml \
  -e "packages_registry_deploy_ref=${GITHUB_SHA}"
```

The workflow then performs an independent HTTPS Registry v1 smoke check. Any
SSH, inventory, Ansible, Nginx, rollback, or smoke-check failure leaves the
workflow red. Optional Environment protection rules may require approval before
the job receives Production credentials.

## Release layout and validation

```text
/opt/open-city-planner-packages/
├── repo/                 single managed Git checkout
├── releases/<sha>/       independent git-archive snapshot and .venv
├── current -> releases/<sha>
├── artifacts/modules/    append-only `.ocp` mirror, never release-pruned
├── tools/uv/             pinned uv tooling venv
└── .uv-cache/            service-user-owned dependency cache
```

An incomplete existing SHA directory is removed and rebuilt. A release carrying
`.release-ready` is reused but still revalidated. Before the marker and symlink
switch, every deploy runs locked sync, Ruff, optional-on-by-default tests, the
existing registry validator and builder, deterministic `dist/` comparison, and
the whitespace check. Validation and deterministic build cannot be disabled.
`dist/index.json` must be a non-empty regular Registry v1 file.

The service user owns checkout, releases, builds, and the uv cache; release
directories are `0755`, generated JSON inherits read access for Nginx, and
`www-data` receives no write access to release content. The disk-space gate
defaults to 512 MiB through `packages_registry_min_release_free_bytes`.

## Nginx, smoke checks, and rollback

The managed vhost redirects HTTP to HTTPS while preserving the ACME challenge.
HTTPS serves static JSON from `current/dist`, disables directory listing, sends
`application/json`, five-minute cache headers, `nosniff`, and no wildcard CORS.
Canonical `/modules/<id>/<version>/<id>-<version>.ocp` routes use the persistent
artifact store, `application/octet-stream`, `nosniff`, and one-year immutable
cache headers. There is no proxy, SPA fallback, or executable content handler.

Ansible validates Nginx before every reload. Activation switches `current`,
reloads Nginx, and checks the local TLS vhost for HTTP 200, JSON content type,
cache header, and `schema_version == 1`. The external HTTPS check validates the
public certificate by default; it can be disabled only for a deliberately
offline staging run with `packages_registry_run_external_smoke_check=false`.
An empty module list is valid.

If activation, reload, or a smoke check fails, Ansible restores the previous
symlink, validates/reloads Nginx, verifies the restored Registry v1 response,
and still reports the original deployment error. On a failed first deployment,
there is no rollback target, so the broken `current` link is removed. Failures
before activation never touch the active release.

After a successful smoke check, mtime-based retention keeps five releases by
default. The active release and the release that was active at the start of the
deploy are protected from that run's pruning. Retention searches only
`releases/`; it never traverses or removes `artifacts/`.

## Explicit artifact publication

Artifact publication is deliberately separate from Registry deployment. It
selects the source URL and expected digest from a completely validated deployed
Registry SHA; operators cannot provide a source URL or destination path.

```bash
uv run ansible-playbook -i inventory/production.ini playbooks/publish-artifact.yml \
  -e registry_ref=<40-character-deployed-registry-sha> \
  -e module_id=analysis-areas \
  -e version=1.0.0
```

The playbook requires the exact `releases/<registry-sha>/.release-ready` marker
before running `scripts/publish_artifacts.py` as `ocp-packages`. The script uses
the Registry artifact gate's URL/redirect limits and streaming downloader,
checks SHA-256, flushes the completed temporary file, and atomically creates the
canonical target without overwrite. A matching existing file reports
`already-present`; a different digest fails closed. Files are `0644`, directories
are `0755`, and `www-data` has read access but no write ownership.

The merged Registry PR already ran the pinned Host verifier against the same
immutable URL and digest. The production playbook deliberately relies on that
reviewed gate instead of installing the Host and Node.js on the static registry
server. A prepared pinned checkout can still be supplied directly to the Python
CLI with `--host-verifier-root` for an additional read-only `verify` pass.

After publication, check the public bytes before opening the separate URL
promotion PR:

```bash
curl --fail --show-error --output /tmp/analysis-areas-1.0.0.ocp \
  https://packages.stadtplaner.oklabflensburg.de/modules/analysis-areas/1.0.0/analysis-areas-1.0.0.ocp
sha256sum /tmp/analysis-areas-1.0.0.ocp
```

The expected SHA-256 is
`7006f31ea73f40e38f63d2065652c27ad5d3391ddcc8cfad2f149993efef3dcf`.
Only after this production proof should a second reviewed Registry PR promote
`artifact.url` from GitHub to the canonical Registry URL. Issue #8 remains open
until both the public mirror and that metadata promotion are complete.

## Operations and troubleshooting

```bash
readlink -f /opt/open-city-planner-packages/current
ls -la /opt/open-city-planner-packages/releases/
find /opt/open-city-planner-packages/artifacts/modules -type f -name '*.ocp' -print
curl --fail --show-error https://packages.stadtplaner.oklabflensburg.de/index.json
sudo nginx -t
```

The safest manual rollback is a normal deployment with a previous SHA. In an
emergency, an operator may switch the link and validate before reload:

```bash
sudo ln -sfn /opt/open-city-planner-packages/releases/<old-sha> \
  /opt/open-city-planner-packages/current
sudo nginx -t
sudo systemctl reload nginx
curl --fail --show-error \
  https://packages.stadtplaner.oklabflensburg.de/index.json
```

Common failures are a dirty managed checkout, missing TLS files, insufficient
disk space, a non-symlink `current` path, a stale committed `dist/`, or public
DNS still reaching another server.
