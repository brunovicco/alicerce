"""Trusted pure policy for authorizing commands before adapter invocation."""

from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn, cast

from alicerce.domain.command import (
    CommandAction,
    CommandLimits,
    CommandRequest,
    EnvironmentVariable,
    ExecutableId,
    NetworkPolicy,
    WorkingDirectory,
)
from alicerce.domain.contracts import Actions
from alicerce.domain.run_identity import PolicyHash


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


def _require_tuple(value: object, *, name: str) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{name} must be a tuple")
    return cast(tuple[object, ...], value)


@dataclass(frozen=True, slots=True)
class CommandRule:
    """One exact trusted action, executable, argv, and capability rule."""

    action: CommandAction
    executable: ExecutableId
    arguments: tuple[str, ...]
    working_directory: WorkingDirectory
    environment_names: tuple[str, ...]
    network_policy: NetworkPolicy
    max_limits: CommandLimits

    def __post_init__(self) -> None:
        """Require deterministic rule components without normalization."""
        _require_instance(self.action, name="action", expected=CommandAction)
        _require_instance(self.executable, name="executable", expected=ExecutableId)
        arguments = _require_tuple(self.arguments, name="arguments")
        for argument in arguments:
            if not isinstance(argument, str):
                raise TypeError("rule argument must be a string")
            if "\0" in argument:
                raise ValueError("rule argument cannot contain NUL")
        _require_instance(
            self.working_directory,
            name="working_directory",
            expected=WorkingDirectory,
        )
        raw_names = _require_tuple(self.environment_names, name="environment_names")
        names: list[str] = []
        for raw_name in raw_names:
            if not isinstance(raw_name, str):
                raise TypeError("environment name must be a string")
            EnvironmentVariable(raw_name, "")
            names.append(raw_name)
        if tuple(names) != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("environment_names must be unique and sorted")
        _require_instance(
            self.network_policy,
            name="network_policy",
            expected=NetworkPolicy,
        )
        _require_instance(self.max_limits, name="max_limits", expected=CommandLimits)


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    """Run-pinned canonical actions plus exact trusted execution rules."""

    policy_hash: PolicyHash
    actions: Actions
    rules: tuple[CommandRule, ...]

    def __post_init__(self) -> None:
        """Reject rule ambiguity and rules outside canonical contract actions."""
        _require_instance(self.policy_hash, name="policy_hash", expected=PolicyHash)
        actions = _require_instance(self.actions, name="actions", expected=Actions)
        raw_rules = _require_tuple(self.rules, name="rules")
        rules = tuple(
            _require_instance(rule, name="rule", expected=CommandRule) for rule in raw_rules
        )
        keys = tuple(_rule_key(rule) for rule in rules)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("rules must be unique and sorted")
        allowed = set(actions.allowed)
        denied = set(actions.denied)
        for rule in rules:
            if rule.action.value not in allowed or rule.action.value in denied:
                raise ValueError("rule action must be canonically allowed and not denied")


class CommandAuthorizationErrorCause(StrEnum):
    """Stable reasons that trusted policy denies a command."""

    POLICY_HASH_MISMATCH = "policy_hash_mismatch"
    ACTION_DENIED = "action_denied"
    EXECUTABLE_DENIED = "executable_denied"
    ARGUMENTS_DENIED = "arguments_denied"
    WORKING_DIRECTORY_DENIED = "working_directory_denied"
    ENVIRONMENT_DENIED = "environment_denied"
    LIMIT_EXCEEDED = "limit_exceeded"


class CommandAuthorizationError(RuntimeError):
    """Raised before executor invocation when trusted policy denies a request."""

    def __init__(self, cause: CommandAuthorizationErrorCause, detail: str) -> None:
        """Record a stable typed cause without candidate-output interpretation."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


@dataclass(frozen=True, slots=True)
class AuthorizedCommand:
    """Command proven to match one run-pinned trusted rule."""

    request: CommandRequest
    policy: CommandPolicy
    rule: CommandRule

    def __post_init__(self) -> None:
        """Prevent construction with a stale, unrelated, or weaker rule."""
        request = _require_instance(self.request, name="request", expected=CommandRequest)
        policy = _require_instance(self.policy, name="policy", expected=CommandPolicy)
        rule = _require_instance(self.rule, name="rule", expected=CommandRule)
        if _matching_rule(request, policy) != rule:
            raise ValueError("rule does not authorize the command request")


def _rule_key(rule: CommandRule) -> tuple[object, ...]:
    return (
        rule.action.value,
        rule.executable.value,
        rule.arguments,
        rule.working_directory.value,
        rule.environment_names,
        rule.network_policy.value,
        rule.max_limits.timeout_ms,
        rule.max_limits.termination_grace_ms,
        rule.max_limits.stdout_max_bytes,
        rule.max_limits.stderr_max_bytes,
    )


def _deny(cause: CommandAuthorizationErrorCause, detail: str) -> NoReturn:
    raise CommandAuthorizationError(cause, detail)


def _matching_rule(request: CommandRequest, policy: CommandPolicy) -> CommandRule:
    if request.run_identity.policy_hash != policy.policy_hash:
        _deny(CommandAuthorizationErrorCause.POLICY_HASH_MISMATCH, "run policy identity changed")

    action = request.action.value
    if action not in policy.actions.allowed or action in policy.actions.denied:
        _deny(CommandAuthorizationErrorCause.ACTION_DENIED, action)

    candidates = [rule for rule in policy.rules if rule.action == request.action]
    if not candidates:
        _deny(CommandAuthorizationErrorCause.ACTION_DENIED, action)

    candidates = [rule for rule in candidates if rule.executable == request.executable]
    if not candidates:
        _deny(CommandAuthorizationErrorCause.EXECUTABLE_DENIED, request.executable.value)

    candidates = [rule for rule in candidates if rule.arguments == request.arguments]
    if not candidates:
        _deny(CommandAuthorizationErrorCause.ARGUMENTS_DENIED, "argv does not match trusted rule")

    candidates = [
        rule for rule in candidates if rule.working_directory == request.working_directory
    ]
    if not candidates:
        _deny(
            CommandAuthorizationErrorCause.WORKING_DIRECTORY_DENIED,
            request.working_directory.value,
        )

    environment_names = tuple(entry.name for entry in request.environment)
    candidates = [
        rule
        for rule in candidates
        if set(environment_names).issubset(rule.environment_names)
        and rule.network_policy is request.network_policy
    ]
    if not candidates:
        _deny(
            CommandAuthorizationErrorCause.ENVIRONMENT_DENIED,
            "environment or network authority exceeds trusted rule",
        )

    for rule in candidates:
        maximum = rule.max_limits
        requested = request.limits
        if (
            requested.timeout_ms <= maximum.timeout_ms
            and requested.termination_grace_ms <= maximum.termination_grace_ms
            and requested.stdout_max_bytes <= maximum.stdout_max_bytes
            and requested.stderr_max_bytes <= maximum.stderr_max_bytes
        ):
            return rule
    _deny(CommandAuthorizationErrorCause.LIMIT_EXCEEDED, "requested ceiling exceeds policy")


def authorize_command(request: CommandRequest, policy: CommandPolicy) -> AuthorizedCommand:
    """Authorize a request completely before any executor can observe it."""
    trusted_request = _require_instance(request, name="request", expected=CommandRequest)
    trusted_policy = _require_instance(policy, name="policy", expected=CommandPolicy)
    return AuthorizedCommand(
        request=trusted_request,
        policy=trusted_policy,
        rule=_matching_rule(trusted_request, trusted_policy),
    )
