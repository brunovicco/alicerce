# Phase 2A Contract Source Identity

Status: Accepted
Decision date: 2026-07-19

## Decision

The Phase 2A contract identity is the lowercase SHA-256 digest of the exact
UTF-8 JSON bytes that were decoded, validated, and used to construct the
canonical `loop_schemas.models.Contract` instance.

Alicerce does not rewrite, normalize, or semantically canonicalize those bytes
before hashing. Whitespace, newline, encoding, field-order, and content changes
therefore produce a different contract identity. This is intentional: the hash
identifies the reviewed source artifact, not merely an equivalent Python value.

## Binding invariant

`BoundContract` binds three values:

- the exact immutable source bytes;
- the canonical `Contract` derived from those bytes;
- the SHA-256 digest of those same bytes.

Direct construction revalidates all three values. `RunIdentity` creation accepts
a `BoundContract`, never an independently supplied contract and digest pair.

## Validation policy

- Input must be exact `bytes` containing UTF-8 JSON.
- The top-level JSON value must be an object.
- Duplicate object keys and non-finite numbers fail closed.
- The decoded document validates through the pinned canonical validator.
- Validation errors use typed internal causes and are not canonical final states.
- Source content is not retained in exception messages.

## Deferred formats

YAML is outside this increment. Adding it requires a separate decision covering
dependency policy and whether identity applies to original YAML bytes or a
document derived from them. Filesystem acquisition remains behind a future
`ContractPort`; this decision operates only on caller-supplied bytes.

## Acceptance impact

- A02 gains executable evidence that the pinned canonical model and validator
  construct the bound contract.
- The contract/hash correspondence gap within A03 is closed.
- A03 is satisfied by immutable value tests, durable identity persistence,
  whole-checkpoint CAS, and resume rejection of changed contract, baseline, or
  policy bindings. See [Resume identity validation](resume-identity-validation.md).
- A08 remains open until candidate, specification, output, environment, and
  evidence bindings are implemented.
