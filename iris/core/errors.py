"""IRIS error hierarchy."""

from __future__ import annotations


class IRISError(Exception):
    """Base exception for all IRIS errors."""


class ConfigError(IRISError):
    """Configuration-related errors."""


class ProviderError(IRISError):
    """LLM provider errors."""

    def __init__(self, message: str, provider: str = "", status_code: int = 0, retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


class AuthenticationError(ProviderError):
    """Invalid or missing API key."""

    def __init__(self, message: str = "Invalid or missing API key", provider: str = ""):
        super().__init__(message, provider=provider, status_code=401, retryable=False)


class RateLimitError(ProviderError):
    """Rate limit exceeded."""

    def __init__(self, message: str = "Rate limit exceeded", provider: str = "", retry_after: float = 0):
        super().__init__(message, provider=provider, status_code=429, retryable=True)
        self.retry_after = retry_after


class ContextLengthError(ProviderError):
    """Context window exceeded."""

    def __init__(self, message: str = "Context length exceeded", provider: str = ""):
        super().__init__(message, provider=provider, status_code=400, retryable=False)


class ToolError(IRISError):
    """Tool execution errors."""

    def __init__(self, message: str, tool_name: str = ""):
        super().__init__(message)
        self.tool_name = tool_name


class ToolNotFoundError(ToolError):
    """Requested tool does not exist."""


class ToolValidationError(ToolError):
    """Tool arguments failed validation."""


class AgentError(IRISError):
    """Agent loop errors."""


class CancellationError(AgentError):
    """Agent run was cancelled."""


class SessionError(IRISError):
    """Session/checkpoint errors."""


class UIError(IRISError):
    """UI-related errors."""


class SkillError(IRISError):
    """Skill loading or execution errors."""


class MCPError(IRISError):
    """MCP protocol errors."""


class MCPConnectionError(MCPError):
    """Failed to connect to an MCP server."""


class MCPTimeoutError(MCPError):
    """MCP request timed out."""
