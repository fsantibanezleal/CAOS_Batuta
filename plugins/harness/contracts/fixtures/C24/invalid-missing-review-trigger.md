<!-- why: review_trigger is required -->
<!-- expect: 'review_trigger' -->
---
id: ADR-0003
title: Use FastAPI for the HTTP API
status: Accepted
date: 2026-10-11
deciders: [alex]
tech_evaluations: [api-framework]
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
