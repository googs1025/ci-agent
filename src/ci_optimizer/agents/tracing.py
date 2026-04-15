"""Langfuse tracing integration.

Provides a thin wrapper around Langfuse SDK. When LANGFUSE_SECRET_KEY
is not configured, all tracing is silently disabled — zero impact on
existing behavior.

Usage in other modules:

    from ci_optimizer.agents.tracing import get_langfuse, langfuse_observe

    @langfuse_observe(name="my-function")
    async def my_function(...):
        ...
"""

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

_langfuse_instance = None
_langfuse_enabled: bool | None = None  # None = not yet checked


def _ensure_init():
    """Lazy-initialize Langfuse on first use (after load_dotenv has run)."""
    global _langfuse_instance, _langfuse_enabled

    if _langfuse_enabled is not None:
        return  # already initialized

    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")

    if not secret_key or not public_key:
        _langfuse_enabled = False
        logger.debug("Langfuse not configured (missing keys)")
        return

    try:
        from langfuse import Langfuse

        _langfuse_instance = Langfuse(
            secret_key=secret_key,
            public_key=public_key,
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        _langfuse_enabled = True
        logger.info("Langfuse tracing enabled (host=%s)", os.getenv("LANGFUSE_HOST", "cloud"))
    except Exception as e:
        _langfuse_enabled = False
        logger.warning("Failed to initialize Langfuse: %s", e)


def get_langfuse():
    """Return the Langfuse client instance, or None if not configured."""
    _ensure_init()
    return _langfuse_instance


def is_enabled() -> bool:
    """Return True if Langfuse tracing is active."""
    _ensure_init()
    return bool(_langfuse_enabled)


def flush():
    """Flush pending Langfuse events. Call at end of background tasks."""
    if _langfuse_instance:
        try:
            _langfuse_instance.flush()
        except Exception as e:
            logger.debug("Langfuse flush error: %s", e)


def langfuse_observe(name: str | None = None, **kwargs: Any) -> Callable:
    """Decorator that wraps langfuse @observe() when enabled, otherwise a no-op.

    Uses lazy check so the decorator resolves at call time, not import time.
    """

    def decorator(func: Callable) -> Callable:
        async def async_wrapper(*args: Any, **kw: Any) -> Any:
            _ensure_init()
            if _langfuse_enabled:
                try:
                    from langfuse.decorators import observe

                    wrapped = observe(name=name or func.__name__, **kwargs)(func)
                    return await wrapped(*args, **kw)
                except Exception:
                    pass
            return await func(*args, **kw)

        def sync_wrapper(*args: Any, **kw: Any) -> Any:
            _ensure_init()
            if _langfuse_enabled:
                try:
                    from langfuse.decorators import observe

                    wrapped = observe(name=name or func.__name__, **kwargs)(func)
                    return wrapped(*args, **kw)
                except Exception:
                    pass
            return func(*args, **kw)

        import inspect

        if inspect.iscoroutinefunction(func):
            async_wrapper.__name__ = func.__name__
            async_wrapper.__doc__ = func.__doc__
            return async_wrapper
        else:
            sync_wrapper.__name__ = func.__name__
            sync_wrapper.__doc__ = func.__doc__
            return sync_wrapper

    return decorator
