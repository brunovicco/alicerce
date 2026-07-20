"""Tests for trusted command authorization before executor invocation."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from alicerce.application.command_execution import execute_authorized_command
from alicerce.domain.command import (
    CommandAction,
    CommandLimits,
    CommandRequest,
    EnvironmentVariable,
    ExecutableId,
    ExecutionResult,
    ExecutionTermination,
    NetworkPolicy,
    WorkingDirectory,
)
from alicerce.domain.command_policy import (
    AuthorizedCommand,
    CommandAuthorizationError,
    CommandAuthorizationErrorCause,
    CommandPolicy,
    CommandRule,
    authorize_command,
)
from alicerce.domain.contracts import Actions
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
    RunIdentity,
)
from alicerce.domain.workspace import WorkspaceId, WorkspaceIdentity

NOW = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)


def _identity(policy_hash: str = "c" * 64) -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-policy"),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("0.1.2"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash(policy_hash),
        created_at=NOW,
    )


def _limits(value: int = 100) -> CommandLimits:
    return CommandLimits(value, value, value, value)


def _request(**changes: object) -> CommandRequest:
    identity = _identity()
    values: dict[str, object] = {
        "run_identity": identity,
        "workspace": WorkspaceIdentity(
            WorkspaceId("workspace-policy"),
            identity.run_id,
            identity.baseline_sha,
        ),
        "action": CommandAction("tests"),
        "executable": ExecutableId("python"),
        "arguments": ("-m", "pytest"),
        "working_directory": WorkingDirectory("."),
        "environment": (EnvironmentVariable("LANG", "C.UTF-8"),),
        "network_policy": NetworkPolicy.DENY_ALL,
        "limits": _limits(50),
    }
    values.update(changes)
    return CommandRequest(**values)  # type: ignore[arg-type]


def _rule(**changes: object) -> CommandRule:
    values: dict[str, object] = {
        "action": CommandAction("tests"),
        "executable": ExecutableId("python"),
        "arguments": ("-m", "pytest"),
        "working_directory": WorkingDirectory("."),
        "environment_names": ("LANG",),
        "network_policy": NetworkPolicy.DENY_ALL,
        "max_limits": _limits(100),
    }
    values.update(changes)
    return CommandRule(**values)  # type: ignore[arg-type]


def _policy(*rules: CommandRule, actions: Actions | None = None) -> CommandPolicy:
    return CommandPolicy(
        policy_hash=PolicyHash("c" * 64),
        actions=actions or Actions(allowed=("tests",), denied=()),
        rules=rules or (_rule(),),
    )


def test_rule_preserves_exact_trusted_command_and_maxima() -> None:
    rule = _rule()
    assert rule.arguments == ("-m", "pytest")
    assert rule.environment_names == ("LANG",)
    assert rule.max_limits.timeout_ms == 100


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _rule(action=object()),
        lambda: _rule(executable=object()),
        lambda: _rule(arguments=["arg"]),
        lambda: _rule(arguments=(1,)),
        lambda: _rule(arguments=("bad\0arg",)),
        lambda: _rule(working_directory=object()),
        lambda: _rule(environment_names=["LANG"]),
        lambda: _rule(environment_names=(1,)),
        lambda: _rule(environment_names=("BAD-NAME",)),
        lambda: _rule(environment_names=("Z", "A")),
        lambda: _rule(environment_names=("A", "A")),
        lambda: _rule(network_policy="deny_all"),
        lambda: _rule(max_limits=object()),
    ],
)
def test_rule_rejects_type_confusion_and_nondeterminism(
    factory: Callable[[], object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_policy_accepts_sorted_unique_rules_with_canonical_actions() -> None:
    first = _rule(executable=ExecutableId("python"))
    second = _rule(executable=ExecutableId("uv"))
    policy = _policy(first, second)
    assert policy.rules == (first, second)
    assert isinstance(policy.actions, Actions)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: replace(_policy(), policy_hash=object()),
        lambda: replace(_policy(), actions=object()),
        lambda: replace(_policy(), rules=[_rule()]),
        lambda: replace(_policy(), rules=(object(),)),
        lambda: _policy(
            _rule(executable=ExecutableId("uv")),
            _rule(executable=ExecutableId("python")),
        ),
        lambda: _policy(_rule(), _rule()),
        lambda: _policy(
            _rule(),
            actions=Actions(allowed=("other",), denied=()),
        ),
        lambda: _policy(
            _rule(),
            actions=Actions(allowed=("tests",), denied=("tests",)),
        ),
    ],
)
def test_policy_rejects_invalid_or_ambiguous_rules(factory: Callable[[], object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_authorization_returns_a_command_bound_to_exact_policy_rule() -> None:
    request = _request(limits=_limits(25), environment=())
    policy = _policy()
    authorized = authorize_command(request, policy)
    assert authorized.request is request
    assert authorized.policy is policy
    assert authorized.rule == _rule()


def test_authorization_rejects_changed_run_policy_hash() -> None:
    request = _request()
    policy = replace(_policy(), policy_hash=PolicyHash("d" * 64))
    with pytest.raises(CommandAuthorizationError) as denied:
        authorize_command(request, policy)
    assert denied.value.cause is CommandAuthorizationErrorCause.POLICY_HASH_MISMATCH


@pytest.mark.parametrize(
    ("command_request", "policy", "cause"),
    [
        (
            _request(),
            CommandPolicy(
                PolicyHash("c" * 64),
                Actions(allowed=("other",), denied=()),
                (),
            ),
            CommandAuthorizationErrorCause.ACTION_DENIED,
        ),
        (
            _request(),
            CommandPolicy(
                PolicyHash("c" * 64),
                Actions(allowed=("tests",), denied=()),
                (),
            ),
            CommandAuthorizationErrorCause.ACTION_DENIED,
        ),
        (
            _request(executable=ExecutableId("uv")),
            _policy(),
            CommandAuthorizationErrorCause.EXECUTABLE_DENIED,
        ),
        (
            _request(arguments=("-c", "pass")),
            _policy(),
            CommandAuthorizationErrorCause.ARGUMENTS_DENIED,
        ),
        (
            _request(working_directory=WorkingDirectory("src")),
            _policy(),
            CommandAuthorizationErrorCause.WORKING_DIRECTORY_DENIED,
        ),
        (
            _request(environment=(EnvironmentVariable("PATH", "bin"),)),
            _policy(),
            CommandAuthorizationErrorCause.ENVIRONMENT_DENIED,
        ),
        (
            _request(limits=_limits(101)),
            _policy(),
            CommandAuthorizationErrorCause.LIMIT_EXCEEDED,
        ),
    ],
)
def test_authorization_denials_have_stable_typed_causes(
    command_request: CommandRequest,
    policy: CommandPolicy,
    cause: CommandAuthorizationErrorCause,
) -> None:
    with pytest.raises(CommandAuthorizationError) as denied:
        authorize_command(command_request, policy)
    assert denied.value.cause is cause
    assert str(denied.value).startswith(f"{cause.value}: ")


def test_authorize_command_rejects_wrong_semantic_types() -> None:
    with pytest.raises(TypeError, match="request must be CommandRequest"):
        authorize_command(object(), _policy())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="policy must be CommandPolicy"):
        authorize_command(_request(), object())  # type: ignore[arg-type]


def test_authorized_command_cannot_substitute_an_unmatched_rule() -> None:
    request = _request()
    policy = _policy()
    with pytest.raises(ValueError, match="rule does not authorize"):
        AuthorizedCommand(
            request=request,
            policy=policy,
            rule=_rule(executable=ExecutableId("uv")),
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AuthorizedCommand(object(), _policy(), _rule()),  # type: ignore[arg-type]
        lambda: AuthorizedCommand(_request(), object(), _rule()),  # type: ignore[arg-type]
        lambda: AuthorizedCommand(_request(), _policy(), object()),  # type: ignore[arg-type]
    ],
)
def test_authorized_command_rejects_type_confusion(factory: Callable[[], object]) -> None:
    with pytest.raises(TypeError):
        factory()


class CountingExecutor:
    """Test-only executor proving denial happens before port invocation."""

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, command: AuthorizedCommand) -> ExecutionResult:
        self.calls += 1
        return ExecutionResult(
            request=command.request,
            termination=ExecutionTermination.EXITED,
            exit_code=0,
            stdout=b"ok",
            stderr=b"",
            started_at=NOW,
            finished_at=NOW,
        )


def test_use_case_invokes_executor_only_after_complete_authorization() -> None:
    executor = CountingExecutor()
    result = execute_authorized_command(_request(), _policy(), executor)
    assert result.exit_code == 0
    assert executor.calls == 1


def test_use_case_denial_keeps_executor_call_count_at_zero() -> None:
    executor = CountingExecutor()
    with pytest.raises(CommandAuthorizationError):
        execute_authorized_command(
            _request(executable=ExecutableId("uv")),
            _policy(),
            executor,
        )
    assert executor.calls == 0


def test_policy_values_are_frozen_slotted_and_cause_vocabulary_is_stable() -> None:
    policy = _policy()
    authorized = authorize_command(_request(), policy)
    assert all(not hasattr(value, "__dict__") for value in (policy.rules[0], policy, authorized))
    with pytest.raises(FrozenInstanceError):
        policy.rules = ()  # type: ignore[misc]
    assert tuple(cause.value for cause in CommandAuthorizationErrorCause) == (
        "policy_hash_mismatch",
        "action_denied",
        "executable_denied",
        "arguments_denied",
        "working_directory_denied",
        "environment_denied",
        "limit_exceeded",
    )
