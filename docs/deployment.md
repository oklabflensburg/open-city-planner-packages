# Static deployment contract

`scripts/build_registry.py` validates source and creates the complete deployment artifact under `dist/`:

```text
dist/
├── index.json
└── modules/
    └── <module-id>.json
```

Publish `index.json` and `modules/` from the same build. Build into a staging release directory and atomically switch a symlink (or use an equivalent atomic object-storage release) so consumers never observe an index and metadata from different builds. Deployment runs only from the protected main branch after merge; pull-request workflows validate data and never receive deployment secrets.

The target is `packages.stadtplaner.oklabflensburg.de`. A static Nginx deployment needs no proxy process:

```nginx
server {
    server_name packages.stadtplaner.oklabflensburg.de;
    root /var/www/open-city-planner-packages/current;

    location / {
        try_files $uri =404;
    }

    location = /index.json {
        default_type application/json;
        add_header Cache-Control "public, max-age=300" always;
        try_files $uri =404;
    }

    location /modules/ {
        default_type application/json;
        add_header Cache-Control "public, max-age=300" always;
        try_files $uri =404;
    }
}
```

Serve JSON as `application/json`. If versioned `.ocp` artifacts are mirrored later, use `application/octet-stream` until a custom media type is standardized and `Cache-Control: public, max-age=31536000, immutable`; mirrored bytes must retain the registry digest. Index and module metadata use shorter caching because channel pointers and new versions may change. Static servers may provide ETags.

Do not enable wildcard CORS without a concrete browser consumer requirement. The primary consumers are server-side/admin tooling. No production secret, tokenized private URL, domain automation, search endpoint, pagination layer, or API server belongs in this artifact.

Registry availability is only needed for pre-install discovery/download. Runtime startup, migrations, and already installed modules make no registry request. The host's `modules.lock`, not this registry, remains authoritative for installed and enabled state.
