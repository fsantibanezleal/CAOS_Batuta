<!-- why: supersedes lists ADR ids -->
<!-- expect: front matter /supersedes/0 -->
---
id: ADR-0003
title: Use FastAPI for the HTTP API
status: Accepted
date: 2026-10-11
deciders: [alex]
review_trigger: review-by: 2027-04-11
tech_evaluations: [api-framework]
supersedes: [old]
---

## Context

We need an async API.

## Decision

FastAPI.

## Alternatives considered

Flask, Django.

## Consequences

Typed models.

## Validation

docs/design/tech/api-framework.json
