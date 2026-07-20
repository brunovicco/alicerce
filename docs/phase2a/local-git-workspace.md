# Local Git Workspace Adapter

Status: Implemented
Decision date: 2026-07-20

## Scope

`LocalGitWorkspace` implements the complete provider-neutral `WorkspacePort`
over standalone local Git clones. It owns the mapping from opaque
`WorkspaceId` capabilities to host paths and never returns those paths through
the port.

The adapter receives trusted configuration at construction:

- an absolute local source repository;
- an existing absolute workspace root;
- existing absolute protected roots;
- the controlled Git CLI primitive;
- a structural `WorkspaceIdGeneratorPort`.

All configured paths are resolved strictly. The workspace root must be
structurally disjoint from the source repository and every protected root. The
source is always protected even when callers do not repeat it in the protected
root tuple.

The capability mapping and run index are intentionally process-local. A new
adapter instance cannot recover an earlier mapping. Persistence and resume are
separate increments.

## Prepare and load

`prepare` rejects duplicate runs and capability collisions before publishing a
record. It creates only the direct child named by the validated `WorkspaceId`,
materializes the exact detached baseline through `ControlledGitCli`, verifies
that no remote remains, records the digest of `.git/config`, and rejects any
workspace symlink resolving outside the workspace.

The record becomes visible only after every check passes. Failed preparation
removes only the unpublished direct child on a best-effort basis.

`load` resolves only capabilities held in the private mapping and revalidates:

- workspace-root identity;
- direct-child capability mapping;
- directory and `.git` integrity;
- the recorded Git configuration digest;
- absence of escaping or invalid symlinks;
- exact `HEAD^{commit}` equality with the recorded `BaselineSha`;
- absence of Git remotes.

Unknown capabilities return `None`. Known but corrupt capabilities fail closed
with a typed `WorkspaceError`.

## Candidate snapshot

`snapshot` first performs the complete load validation. The controlled Git
primitive then creates a temporary index outside the candidate checkout,
seeds it from `HEAD`, stages tracked changes and untracked non-ignored files,
and returns `git write-tree` as a semantic `CandidateSha`.

The real Git index and working tree are not changed. Repeating a snapshot of
unchanged content returns the same tree identity. Ignored untracked content is
deliberately excluded; generated artifacts and execution-environment identity
belong to later evidence bindings rather than the candidate source tree.

The adapter repeats its integrity validation after snapshot creation before
returning the `CandidateIdentity` bound to the complete `WorkspaceIdentity`.

## Safe release

`release` requires the exact recorded workspace identity. Missing capabilities
are treated idempotently. A present direct child is atomically renamed to a
capability-specific quarantine inside the workspace root before deletion.

If a race replaces the child with a symlink or non-directory, the adapter
removes only that quarantined directory entry and reports an isolation failure.
Filesystem deletion failures attempt to restore the original name and surface
as storage failures. A later release retries a safely detached quarantine if
rollback could not restore it. Protected and unrelated roots are never release
targets.

## Acceptance impact

A04 gains executable evidence for standalone baseline clones, disjoint trusted
roots, private capability mapping, symlink escape rejection, metadata integrity
checks, and safe idempotent release. A04 remains partial because these checks do
not confine a future process running under the same operating-system identity:
absolute paths, hardlinks, and concurrent filesystem races require the future
`CommandExecutorPort` sandbox and command policy.

A08 gains a deterministic Git tree identity computed by trusted code and bound
to run, baseline, workspace, and capability identity. A08 remains open until
trusted command, environment, specification, artifact, and evidence hashes are
assembled into authoritative evidence.

A11 remains partial. Workspace mappings, candidate identities, and integrity
metadata are not persisted or revalidated by resume in this increment.

A19 remains protected. The adapter and Git primitive expose no network remote,
push, branch promotion, merge, hosting, deployment, or release authority.

## Explicit exclusions

This increment does not implement:

- generic or candidate-controlled subprocess execution;
- OS sandboxing, network policy, allowlists, or secret isolation;
- persisted workspace mapping or cross-process recovery;
- candidate command, gate, evidence, or verdict construction;
- artifact or state-store integration;
- submodule initialization or Git LFS;
- providers, observability, merge, deployment, or release capabilities.
