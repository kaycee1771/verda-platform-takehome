# Scripts

Root scripts are stable operator entrypoints behind the canonical Makefile. Phase 2 infrastructure
orchestration lives in `scripts/infra/`; credentials remain process-only and are never forwarded to
the pinned quality container. Unimplemented phases fail with an owning-phase message and non-zero
status. The exceptional node-02 recovery has dedicated plan/apply targets that require both the
canonical `CONFIRM=--confirm` argument and `CONFIRM_DESTRUCTIVE_ACTION=yes`; its plan assertion
permits one instance/OS replacement and requires the existing persistent data-volume attachment to
remain identical.
