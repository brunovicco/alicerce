# Phase 2A Local Human Review

Status: Accepted
Decision date: 2026-07-19

## Boundary

Phase 2A provides a local `HumanReviewPort` adapter only. It performs no network
request and cannot create or update branches, pull requests, reviews, merges,
deployments, releases, or branch protection.

## Review request

When a contract requires human review and the technical outcome is eligible for
`SUCCEEDED`, the adapter renders a deterministic local review request that
references:

- `run_id`, contract ID, baseline SHA, and candidate SHA;
- authoritative evidence and verdict hashes;
- hard-gate summary;
- changed-file names;
- budget summary;
- open risks and required reviewer roles.

It does not embed prompts, responses, stdout, stderr, diffs, credentials, or
personal data. Evidence remains the authority.

The verdict and request are first prepared through `ArtifactStorePort` as a
single review bundle. The request references the deterministic verdict hash,
but neither artifact becomes authoritative until one atomic commit record
publishes both. Failure to prepare or commit prevents `SUCCEEDED` and maps to
`INFRA_FAILED` or `ESCALATED` according to recoverability.

After a crash, resume reconstructs the verdict from authoritative evidence,
verifies the verdict hash referenced by the prepared request, and commits the
matching bundle idempotently. A mismatch invalidates and quarantines the
prepared request with a typed fail-closed cause. An orphan request is never
authoritative.

## Human decision

Phase 2A does not record approval as a promotion action. A human may inspect the
local artifacts, but merge and deployment remain external and manual.

## Acceptance criteria

- The adapter performs zero network calls.
- Repository credentials are not accepted by its constructor or port.
- Output is deterministic for the same authoritative inputs.
- Sensitive content and raw command output are absent.
- Persistence failure cannot leave a committed successful verdict without its
  required review request.
- Crash recovery cannot leave an authoritative request without its matching
  single-assignment verdict.
- Retrying publication produces exactly one committed review bundle.
- No method exposes merge, deploy, release, or repository mutation.
