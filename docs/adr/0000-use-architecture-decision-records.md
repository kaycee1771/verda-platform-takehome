# ADR 0000: Use Architecture Decision Records

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Platform architecture

## Context

The assignment explicitly evaluates reasoning and tradeoffs. A final architecture diagram cannot explain when a decision was made, which alternatives were considered, or what evidence should reverse it.

## Decision

Use immutable, numbered ADRs for material platform decisions. Later changes supersede an ADR rather than rewriting its historical reasoning.

Every ADR must include context, decision, alternatives, consequences, validation, and reversal triggers.

## Alternatives considered

- **Architecture prose only:** rejected because later changes would erase decision history and validation criteria.
- **Issue tracker only:** useful for work management but not a durable, repository-local architecture record.

## Consequences

- Reviewers can distinguish deliberate constraints from accidental gaps.
- Proposed decisions remain visibly gated instead of silently becoming facts.
- Documentation requires upkeep when observed platform behavior differs from design assumptions.

## Validation evidence

`scripts/phase0/validate.ps1` verifies that every ADR registered in `config/phase0.json` exists and has a recognized status.

## Production evolution

Adopt the organization's formal decision-review workflow and ownership model while retaining immutable supersession and evidence links.
