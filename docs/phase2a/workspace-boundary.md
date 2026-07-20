# Isolated Workspace Boundary

Status: Implemented
Decision date: 2026-07-20

## Scope

This increment defines immutable workspace and candidate identities plus the
provider-neutral `WorkspacePort`. It deliberately contains no filesystem, Git,
worktree, command, or subprocess implementation.

The boundary establishes the capability vocabulary that a later trusted local
adapter must implement and that future command and gate ports can consume
without receiving arbitrary host paths.

## Immutable identities

`WorkspaceId` is an opaque, bounded, path-safe capability handle. It is not a
filesystem path and cannot contain separators, whitespace, or a leading dot or
hyphen.

`CandidateSha` is a semantic wrapper for one complete lowercase 40- or
64-character object identity. It is intentionally distinct from `BaselineSha`:
equal digest text does not make the two semantic values interchangeable.

`WorkspaceIdentity` binds:

- one `WorkspaceId`;
- one `RunId`;
- the complete `BaselineSha` already bound into the run identity.

`CandidateIdentity` binds one `CandidateSha` to the complete originating
`WorkspaceIdentity`. Candidate and baseline SHA equality is permitted. Whether
equal content means no work, no progress, or another outcome belongs to future
trusted evaluation, not to identity construction.

Every value is frozen and slotted. Construction rejects bare strings and other
semantic wrapper types in place of the required values.

## Capability boundary

`WorkspacePort` is a structural protocol with four operations:

1. `prepare` receives the complete `RunIdentity` and returns a workspace bound
   to that run and baseline;
2. `load` resolves an existing capability without exposing its host location;
3. `snapshot` returns a trusted candidate identity bound to the current
   workspace;
4. `release` idempotently disposes of a workspace owned by the supplied
   capability.

The protocol never accepts or returns `pathlib.Path` or a raw path string. A
future local adapter owns the private mapping from `WorkspaceId` to its
filesystem directory. Future command execution should consume the capability
through trusted adapters instead of allowing callers to choose a working
directory directly.

Workspace implementations expose stable operational causes:

- `already_exists`;
- `not_found`;
- `conflict`;
- `isolation_failure`;
- `storage_failure`.

## Required adapter invariants

The future local adapter must prove through integration and conformance tests
that:

- candidate content starts from the exact immutable baseline SHA;
- candidate writes cannot modify the trusted checkout;
- candidate writes cannot reach state or artifact stores;
- candidate writes cannot replace trusted gate drivers or configuration;
- workspace ownership matches its run and capability handle;
- snapshot identity is computed by trusted code after candidate activity;
- load rejects ownership, baseline, or integrity mismatches;
- release cannot target an unrelated or protected directory;
- repeated release is safe.

No adapter may treat the capability value itself as an unvalidated relative
path.

## Acceptance impact

A04 gains the provider-neutral isolation boundary and capability model. It
remains partial until a local adapter demonstrates real filesystem separation
and protected-root behavior.

A08 gains an immutable candidate identity bound to run, baseline, and
workspace. It remains open until candidate SHA, trusted specification hashes,
command outputs, environment identity, and evidence hashes are assembled into
authoritative evidence.

A11 gains the types needed to represent workspace and candidate identity. It
remains partial because these values are not yet persisted or revalidated by
resume.

A19 remains protected: the workspace port exposes no repository hosting,
promotion, merge, deployment, or release authority.

## Explicit exclusions

This increment does not implement:

- filesystem directories or path resolution;
- Git, worktrees, commits, branches, or repository mutation;
- workspace serialization or state-store schema changes;
- workspace reconstruction during resume;
- subprocesses, commands, gates, or environment policy;
- artifact or evidence storage;
- provider or observability behavior;
- merge, deployment, or release capabilities.

The in-memory implementation used by the executable port tests exists only
under `tests/` and is not part of the Alicerce runtime package.
