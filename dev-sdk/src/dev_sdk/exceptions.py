"""SDK exceptions for CLI to map to exit codes and messages."""


class DevSdkError(Exception):
    """Base for SDK errors."""


class AgentNotFoundError(DevSdkError):
    """Agent command not found."""


class AgentTimeoutError(DevSdkError):
    """Agent run timed out."""


class AgentRunError(DevSdkError):
    """Agent process exited with failure."""

    def __init__(self, message: str, returncode: int, stderr: str = "", streamed_output: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.streamed_output = streamed_output


class ChatIdNotFoundError(DevSdkError):
    """Chat ID file missing or empty."""
