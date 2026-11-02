---
id: ADR-0003
title: Use FastAPI for the HTTP API
status: Superseded
date: 2026-10-11
deciders: [alex]
review_trigger: the API traffic exceeds 1000 rps
tech_evaluations: []
superseded_by: ADR-0007
supersedes: [ADR-0001]
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
