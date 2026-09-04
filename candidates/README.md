# Registry build candidates

This directory contains small, reviewable provenance records created by `ocp-builder v1`.
Binary `.ocp` candidates stay in the originating GitHub Actions run and are never committed.
A candidate is not a production Registry release and merging it does not publish or promote it.

The split is intentional: source build jobs have read-only permissions and no production secrets;
only a later job may write the provenance branch and open a pull request. No workflow auto-merges.
