"""Trusted internal promotion CLI; never exposed by FastAPI."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from zipfile import BadZipFile

from sqlalchemy.exc import SQLAlchemyError

from scripts.artifact_store import ArtifactStoreError, FilesystemArtifactStore
from scripts.reviewed_candidate import GitHubCandidateSource, download_reviewed_artifact
from web.backend.app.db.config import database_engine
from web.backend.app.registry_promotion import PromotionIntent, RegistryPromotionService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=["stable", "beta", "nightly"], required=True)
    parser.add_argument("--approval-pr", type=int, required=True)
    parser.add_argument(
        "--candidate-sha256", required=True, help="SHA-256 of canonical full candidate"
    )
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--expected-channel-revision", type=int, required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument(
        "--artifact", type=Path, help="Privately materialized exact reviewed bytes"
    )
    sources.add_argument("--download-reviewed-artifact", action="store_true")
    parser.add_argument("--mode", choices=["staging", "production"], required=True)
    parser.add_argument("--confirm-production-promotion", action="store_true")
    args = parser.parse_args()
    if args.mode == "production" and not (
        args.confirm_production_promotion
        and os.environ.get("PACKAGES_REGISTRY_WRITER_CUTOVER_ENABLED") == "true"
    ):
        parser.error("Production requires explicit confirmation and completed writer-cutover gate")
    if args.mode == "staging" and args.confirm_production_promotion:
        parser.error("Production confirmation is not valid in staging mode")
    engine = None
    try:
        # Separate writer credentials; never use the read runtime's DATABASE_URL implicitly.
        variable = (
            "PACKAGES_REGISTRY_PROMOTION_DATABASE_URL"
            if args.mode == "production"
            else "PACKAGES_REGISTRY_STAGING_PROMOTION_DATABASE_URL"
        )
        url = os.environ.get(variable)
        if not url:
            raise ValueError("Explicit promotion database configuration is required")
        reviewer = GitHubCandidateSource()
        intent = PromotionIntent(
            args.module,
            args.version,
            args.approval_pr,
            args.candidate_sha256,
            args.bundle_sha256,
            args.channel,
            args.expected_channel_revision,
            args.idempotency_key,
        )
        engine = database_engine(url)
        with tempfile.TemporaryDirectory(prefix="registry-promotion-") as temporary:
            source = args.artifact
            if args.download_reviewed_artifact:
                reviewed = reviewer.load(
                    args.module, args.version, args.approval_pr, args.candidate_sha256
                )
                source = download_reviewed_artifact(reviewed, Path(temporary))
            service = RegistryPromotionService(
                engine, FilesystemArtifactStore(args.artifact_root), candidate_source=reviewer
            )
            print(json.dumps(service.promote(intent, source), sort_keys=True))
    except (
        SQLAlchemyError,
        ArtifactStoreError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
        BadZipFile,
    ):
        # Neither DB URLs/SQL diagnostics nor untrusted remote error text are printable.
        print("Promotion failed: evidence, artifact, immutable intent or database gate rejected")
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
