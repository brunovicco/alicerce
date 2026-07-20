"""Application use case for mandatory authorization before command execution."""

from alicerce.domain.command import CommandRequest, ExecutionResult
from alicerce.domain.command_policy import CommandPolicy, authorize_command
from alicerce.ports.command_executor import CommandExecutorPort


def execute_authorized_command(
    request: CommandRequest,
    policy: CommandPolicy,
    executor: CommandExecutorPort,
) -> ExecutionResult:
    """Authorize completely before invoking the executor boundary."""
    authorized = authorize_command(request, policy)
    return executor.execute(authorized)
