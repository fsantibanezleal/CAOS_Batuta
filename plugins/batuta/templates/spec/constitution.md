# Constitution

Non-negotiable invariants. They outrank every plan and spec; a plan's constitution check names the article a decision
touches. Amending an article bumps the version below and goes through an ADR.

Version: 1.0

## Article 1: Real, not demo
Build the real thing, scalable and tested. A stand-in exists only at a boundary, labelled, with a plan to replace it.

## Article 2: Spec before code
Every requirement has an id, an EARS text and a gate that can run and fail, written and approved before the code.

## Article 3: Tests first, from an independent oracle
Expected values come from the spec, a closed-form result, a reference implementation or cited values, never from running
the code under test.

## Article 4: Contracts first
Every interface has a versioned data contract and a fallback that honours it and says it is a fallback.

## Article 5: Determinism
Same inputs give the same outputs; tolerances are explicit; outputs are byte-stable.

## Article 6: Honesty
Reports state what was verified and what was not. A claim without evidence is marked unverified.

## Article 7: Simplicity
Prefer the simpler design; the plan states the simpler alternative it rejected and why.

## Tiers

The tier of a spec decides which artifacts it needs.

### Tier S
A small, local change. Artifacts: `spec.md` and `tasks.md`. No plan.

### Tier M
A feature across several files or one contract. Artifacts: Tier S plus `plan.md` with the constitution check.

### Tier L
A feature that crosses units or repositories, or changes a contract. Artifacts: Tier M plus at least one ADR referenced by
the spec, so the freeze hashes it.
