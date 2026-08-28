# Publishing

The release pipeline is deliberately explicit:

1. Develop and test the module in its own repository.
2. Build the host-defined `.ocp` v1 bundle in module CI.
3. Run the pinned host verifier described below.
4. Calculate SHA-256 over the complete `.ocp` file.
5. Publish the immutable, versioned `.ocp` release, preferably as a GitHub Release in the module repository.
6. Add or update `registry/modules/<module-id>.json` in a registry pull request.
7. Run local registry validation and the deterministic build.
8. Obtain registry review and merge only after all CI gates pass.
9. Build and atomically deploy `dist/` as one release.

For example:

```bash
sha256sum energy-analysis-1.4.0.ocp
uv run python scripts/validate_registry.py --base-ref origin/main
uv run python scripts/build_registry.py --output dist
git diff --exit-code -- dist
```

The registry validator checks metadata and publishing policy. It intentionally does not implement a ZIP reader, manifest parser, wheel validator, or frontend validator.

## `.ocp` v1 verification contract

Before a `stable` entry is proposed, verify the downloaded local artifact using the Open City Planner host contract:

```bash
uv run python -m app.cli.modules verify /path/to/energy-analysis-1.4.0.ocp
```

Registry v1 is aligned to host branch `staging/epic-91-modular-host` at commit `b8c4db7f3246d21c53a1b5633915be16bb84a633`. Publishing automation that checks out the host verifier must pin this full commit (or a later explicitly reviewed release tag/commit), never an unpinned `main` HEAD. Complete `.ocp` validation is a mandatory precondition for `stable`; the initial registry CI performs local data validation only because the registry is empty and must not blindly download untrusted pull-request URLs.

When artifact-download CI is added, it must accept only policy-approved URLs, use no secrets for untrusted pull requests, limit size/time, verify the registry digest before parsing, and execute the pinned host verifier without constructing shell commands from metadata. An unreachable artifact cannot be published as `stable`.

Reviewed-community modules follow the same technical pipeline. The additional work is human verification of publisher, public/reviewable source repository, license, maintainer provenance, immutable artifact location, and review evidence; there is no separate community registry.

After discovery, a future admin-side consumer may download a selected `id@version`, verify SHA-256, run `.ocp` verification, and invoke the existing installer. This repository does not implement that consumer, runtime downloads, automatic installation, or transitive dependency selection.
