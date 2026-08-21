# Phase 6 protected-main authorizations

This directory intentionally contains no operation authorization. A future operation requires three separate,
used-once artifacts matching `schemas/phase6-github-authorization.schema.json`, each added in its own pull request:

1. `<operation-id>-prepare.json` binds the reviewed plan, state, journal, gates, and target. It authorizes only
   preparation; it cannot claim the preparation receipt it has not produced.
2. `<operation-id>-apply.json` directly follows and hash-binds the merged prepare authorization, the fresh
   preparation receipt, and the two-survivor collector. It authorizes only the provider apply.
3. `<operation-id>-recover.json` directly follows and hash-binds the merged apply authorization, apply receipt,
   applied state, refreshed host-key/inventory provenance, and recovery collector. It authorizes only recovery.

The verifier requires each GitHub squash-merge commit to change only its exact stage artifact and be the signed
tip of canonical protected `main`, with the pinned validation workflow successful on that PR head. Stage nonces
must be unique. No stage implicitly authorizes the next stage.

The checked-in Phase 6 contract remains inert, and no plan, apply, prepare, adoption, or recovery route consumes
these artifacts yet. Local files, DPAPI material, and self-consistent JSON are not authorization roots.
