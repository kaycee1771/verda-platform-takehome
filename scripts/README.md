# Scripts

Root scripts are stable operator entrypoints behind the canonical Makefile. Unimplemented phases
fail with an owning-phase message and non-zero status; quality implementation lives in
`scripts/quality/` and never receives cloud credentials.
