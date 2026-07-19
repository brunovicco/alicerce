# Phase 2A Package Boundaries

Status: Proposed

## Runtime target

- Python: 3.12, 3.13, and 3.14 for the mandatory core.
- Packaging: `src` layout with deterministic `uv.lock`.
- Canonical schemas source: `engineering-loop-schemas v0.1.2`, source code
  commit `0459d61b7b1d4e7b46709e6d3895770553e6fab0`.
- Schema acquisition: normal locked dependency or deterministic generated
  bundle; the implementation PR must choose one and record provenance.
- Optional observability adapters are outside Phase 2A.

## Proposed layout

```text
src/alicerce/
  domain/          immutable types, policies, state transitions
  application/     use cases and orchestration
  ports/           provider-neutral interfaces
  adapters/local/  filesystem, subprocess, worktree, no-op and local review
tests/
  unit/
  contract/
  integration/
```

## Dependency direction

```text
adapters -> application -> domain
             |
             v
            ports
```

The domain imports neither application nor adapters. Ports expose domain types
and must not expose GitHub, Codex, Claude, OpenTelemetry, A2A, or MCP SDK types.

## Trust boundaries

- Domain and trusted policies are loaded from the installed Alicerce package.
- Canonical serialized contracts validate through the pinned schemas source.
- Candidate files never shadow imports used by the orchestrator or gate driver.
- Builder processes do not receive writable paths to state or artifact stores.
- Local adapters receive the minimum capability required by their port.

## Initial ports

- `ContractPort`
- `WorkspacePort`
- `CommandExecutorPort`
- `GateRunnerPort`
- `StateStorePort`
- `ArtifactStorePort`
- `ProviderPort`
- `ObservabilityPort`
- `HumanReviewPort`
- `ClockPort`
- `IdGeneratorPort`

`ProviderPort` has only a deterministic fake in Phase 2A.

Provider usage observations contain a source identity but no self-declared
trust flag. A trusted, run-pinned `UsageTrustPolicy` maintained by the domain
classifies known sources as advisory or corroborated. Unknown sources are
advisory. Adapters cannot upgrade their own trust classification.

## Acceptance criteria

- A source scan rejects provider-specific identifiers in domain modules.
- Importing the mandatory package does not import provider or telemetry SDKs.
- Tests run on Python 3.12, 3.13, and 3.14.
- The selected schema acquisition mode verifies the full source commit.
- Candidate-controlled `PYTHONPATH` cannot shadow trusted modules.
- All filesystem and subprocess behavior is reachable only through ports.
- The hash of `UsageTrustPolicy` is bound into immutable run identity.
