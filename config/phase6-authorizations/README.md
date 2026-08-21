# Phase 6 protected-main transaction authorizations

This directory contains only the pinned GitHub `web-flow` public key and its
provenance.  A future resize operation may add exactly one file named
`<operation-id>-transaction.json` in a GitHub squash-merge commit on protected
`main`.  The artifact authorizes one inseparable transaction policy, never an
individual low-level mutation.

The tracked Phase 6 contract remains inactive and this repository ships no
consumer, prepare, apply, recovery, or broker route.  The verifier is read-only.
Its JSON receipt is evidence, not a capability, and must never be cached or
trusted.  A future broker must synchronously re-run the verifier while holding
the canonical OS lease immediately before starting the transaction.

The verifier requires the exact public repository, current remote `main`, a
one-parent web-flow-signed squash merge, one newly added authorization file,
the exact app-bound hosted workflow, and live branch/repository governance.
It records the current residual that protected `main` requires zero GitHub
review approvals and has required-signatures disabled; the individual merge
commit must still verify against the pinned web-flow key.  The explicitly
trusted repository owner/admin and user approval are the authority.  A
malicious GitHub administrator is outside this boundary's threat model; local
same-user processes remain untrusted.

The single transaction avoids leaving a quiesced node waiting through more
authorization PRs.  A later broker design must hold one lease and crash-safe
journal through quiesce, provider apply, recovery, postflight, and bounded
rollback.  Starting is allowed only before `start_by`; after a recorded start,
the immutable authorization and journal may permit bounded completion or
rollback without an additional hosted authorization wait.
