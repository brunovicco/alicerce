# Canonical Evidence Serialization and Hashing

Status: Implemented
Decision date: 2026-07-21

## Scope

This increment provides pure trusted primitives for deterministic serialization
and SHA-256 hashing of canonical engineering-loop-schemas v0.2.0 evidence
values. It performs no filesystem access, persistence, gate execution, verdict
construction, orchestration, or remote operation.

The implementation consumes the canonical Environment, CommandResult, Usage,
and Evidence dataclasses directly. Alicerce does not define a competing
serialized evidence model.

## Byte contract

Canonical evidence JSON uses:

- UTF-8 encoding;
- lexicographically sorted object keys;
- compact separators with no insignificant whitespace;
- unescaped Unicode where UTF-8 can represent it;
- standard JSON only, with non-finite numbers rejected;
- explicit null for a forced command termination's exit code;
- omission of estimated_cost_usd only when the canonical optional value is
  absent.

Environment and command-result serializers produce exactly the subdocuments
embedded by the complete evidence serializer. Their hashes can therefore be
recomputed independently without a second representation.

## Hash contract

sha256_bytes hashes exact bytes without decoding or newline normalization.
This is the primitive used for captured stdout, captured stderr, and an
immutable gate specification after that specification has been serialized by
trusted code.

Environment, command-result, and complete-evidence helpers hash their exact
deterministic JSON bytes. Digests are lowercase 64-character hexadecimal
strings matching the canonical schema.

Every value is checked fail-closed before serialization. Unknown termination,
contradictory exit-code state, malformed hashes or object identifiers,
non-finite or negative numeric values, invalid timestamps, wrong container
types, and invalid UTF-8 content are rejected.

## Authority boundary

Deterministic bytes and hashes are necessary but not sufficient for
authoritative evidence. These primitives do not:

- define or execute a trusted gate specification;
- verify the current candidate SHA immediately before evidence assembly;
- persist output blobs or evidence bytes;
- publish an artifact commit record;
- derive a verdict or final state.

Operational-result mapping is implemented separately by
[Trusted command evidence assembly](command-evidence-assembly.md).

Until those steps are implemented and adversarially tested, A08 remains
partial. A missing or unpersisted evidence document cannot produce PASS or
SUCCEEDED.

## Acceptance impact

- A02 remains satisfied because serialization consumes the pinned canonical
  types by identity.
- A08 gains deterministic byte and digest primitives for outputs, environment,
  command results, specification bytes, and the complete evidence document.
- A09 and A19 remain protected because these functions contain no verdict,
  promotion, merge, deployment, release, or GitHub mutation authority.

## Explicit exclusions

- artifact or evidence persistence;
- evidence, gate, verdict, or artifact builders;
- trusted gate specifications and gate execution;
- runner, resume orchestration, budgets, providers, or observability;
- macOS or Windows sandbox backends;
- merge, deployment, release, hosting, or repository mutation.
