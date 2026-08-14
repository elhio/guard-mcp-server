"""
The middleware stack wrapped around every MCP request.

Four concerns, ordered from outside in:

1. Timing and logging, so a slow or failing call leaves a trace. Logs go to stderr,
   which matters because stdout carries the protocol on the stdio transport.
2. Generic error handling, so nothing escapes as an unhandled exception.
3. Rate limiting, in two tiers. A global ceiling covers every message; a much tighter
   budget covers the tools that create billable activities, because an agent in a retry
   loop can otherwise spend real money quickly.
4. Guard error translation, innermost, so `guard_client` exceptions become messages an
   agent can act on before anything more generic sees them.

Examples:
    ```python
    from guard_mcp.middleware import build_middleware

    mcp = FastMCP("guard", middleware=build_middleware(settings))
    ```
"""

from __future__ import annotations

import logging
from typing import Any, List, Sequence

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.rate_limiting import (
    RateLimitingMiddleware,
    TokenBucketRateLimiter,
)
from fastmcp.server.middleware.timing import TimingMiddleware
from guard_client import GuardError

from .errors import to_tool_error
from .settings import GuardMCPSettings

__all__ = ["ActivityRateLimitMiddleware", "GuardErrorMiddleware", "build_middleware"]

logger = logging.getLogger("guard_mcp")

#: Tools that create a billable activity, and so deserve their own budget.
BILLABLE_TOOLS = frozenset({"analyze_media"})


class GuardErrorMiddleware(Middleware):
    """
    Turns `guard_client` exceptions into `ToolError` messages an agent can act on.

    This sits closest to the tool so it sees the original exception, with its status
    code and activity id intact, before any generic handler flattens it.
    """

    async def on_call_tool(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        """
        Run the tool, translating any client failure on the way out.

        Args:
            context: The call being handled.
            call_next: The rest of the pipeline.

        Returns:
            Whatever the tool returned.

        Raises:
            ToolError: The tool raised a `GuardError`. The original is chained so the
                traceback survives in the server log.
        """
        try:
            return await call_next(context)
        except GuardError as exc:
            logger.info("Guard client error in tool call: %s", exc)
            raise to_tool_error(exc) from exc


class ActivityRateLimitMiddleware(Middleware):
    """
    A second, tighter rate limit for the tools that spend tokens.

    Attributes:
        requests_per_minute: How many billable tool calls are allowed per minute.
        tools: The tool names this budget applies to.

    Notes:
        The bucket is global to the server rather than per client. The point is to
        protect the Guard account from a runaway agent, and the account is what every
        caller shares.
    """

    def __init__(
        self,
        requests_per_minute: float = 30.0,
        tools: Sequence[str] = tuple(BILLABLE_TOOLS),
    ) -> None:
        """
        Build the token bucket for the billable tools.

        Args:
            requests_per_minute: Sustained rate allowed.
            tools: The tool names to police.
        """
        self.tools = frozenset(tools)
        self.requests_per_minute = requests_per_minute
        self._limiter = TokenBucketRateLimiter(
            capacity=max(1, int(requests_per_minute)),
            refill_rate=requests_per_minute / 60.0,
        )

    async def on_call_tool(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        """
        Charge a token before running a billable tool.

        Args:
            context: The call being handled.
            call_next: The rest of the pipeline.

        Returns:
            Whatever the tool returned.

        Raises:
            ToolError: The budget is exhausted. The message says how long to wait,
                because an agent that is told only "slow down" will retry immediately.
        """
        name = getattr(context.message, "name", None)
        if name in self.tools and not await self._limiter.consume():
            wait = max(1, round(60.0 / max(self.requests_per_minute, 1e-6)))
            raise ToolError(
                f"This server allows {self.requests_per_minute:.0f} {name} calls per "
                f"minute and that budget is spent. Wait about {wait} seconds before "
                "trying again."
            )
        return await call_next(context)


def build_middleware(settings: GuardMCPSettings) -> List[Middleware]:
    """
    Assemble the middleware stack for a server.

    Args:
        settings: The server settings that tune logging and the rate limits.

    Returns:
        The middleware in the order FastMCP should run them, outermost first.
    """
    return [
        TimingMiddleware(logger=logger),
        LoggingMiddleware(
            logger=logger,
            include_payloads=settings.include_payloads_in_logs,
            max_payload_length=settings.max_payload_log_length,
        ),
        ErrorHandlingMiddleware(logger=logger, include_traceback=False),
        RateLimitingMiddleware(
            max_requests_per_second=settings.max_requests_per_second,
            burst_capacity=settings.burst_capacity,
            global_limit=True,
        ),
        ActivityRateLimitMiddleware(
            requests_per_minute=settings.activity_requests_per_minute
        ),
        GuardErrorMiddleware(),
    ]
