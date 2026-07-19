# Phase 2A Readiness Pack

Status: Approved
Decision date: 2026-07-19
Review required: completed
Implementation authorized by this document: Phase 2A only

## Purpose

This pack converts the approved Phase 2 architecture into testable prerequisites
for the first trusted local-core implementation. It introduces no Python code,
dependencies, schemas, provider adapters, or remote side effects.

The upstream meaning of `NO_PROGRESS` was clarified by
`engineering-loop-schemas` PR #4, merge commit
`585e87447ba7007faf1a51a9f932164afd63d926`. Stall remains an internal signal;
the typed cause and authoritative evidence determine the canonical final state.

Executable contract provenance remains `engineering-loop-schemas v0.1.2` at
source commit `0459d61b7b1d4e7b46709e6d3895770553e6fab0`. The non-serialized
stall clarification is pinned separately to documentation decision
`585e87447ba7007faf1a51a9f932164afd63d926`. That documentation-only decision
does not require a schema release, tag, or consumer revendor.

## Documents

- [Package boundaries](package-boundaries.md)
- [Contract source identity](contract-identity.md)
- [Run lifecycle policy](run-lifecycle.md)
- [State store contract](state-store-contract.md)
- [Trusted gate specifications](trusted-gates.md)
- [Budget accounting](budget-accounting.md)
- [Artifact retention](artifact-retention.md)
- [Local human review](human-review.md)
- [Acceptance matrix](acceptance-matrix.md)
- [Authorization checklist](authorization-checklist.md)

## Scope of Phase 2A

Phase 2A may implement only a local, provider-neutral core with:

- immutable domain types and ports;
- pinned canonical schema integration;
- local state and artifact stores;
- isolated candidate workspaces;
- trusted command and gate execution;
- deterministic evidence and verdict construction;
- conservative budget accounting with a fake provider;
- no-op observability;
- local human-review requests.

Phase 2A may not implement provider SDKs, `a2a-otel-kit`, A2A, MCP protocol
adapters, GitHub mutations, merge, deploy, release, or remote multi-tenant
execution.

## Authorization decision

The readiness review completed the required actions:

1. every policy document in this pack is Accepted;
2. every row in the acceptance matrix is mandatory for implementation;
3. schemas executable and documentation provenance are pinned separately;
4. the architecture proposal grants only Phase 2A authorization;
5. all Phase 2B deferrals remain in force.

This approval authorizes incremental implementation of the trusted local core
against the mandatory acceptance matrix. It does not declare Phase 2A complete.
