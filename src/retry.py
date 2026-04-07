import asyncio
import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def retry_async(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    retry_on_status: list[int] | None = None,
):
    """Decorator for async functions with exponential backoff retry."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    result = await func(*args, **kwargs)
                    # Check for HTTP response status if applicable
                    if hasattr(result, "status_code") and retry_on_status:
                        if result.status_code in retry_on_status:
                            raise Exception(
                                f"Retryable status code: {result.status_code}"
                            )
                    return result
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait = backoff_factor**attempt
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                            f"Retrying in {wait}s..."
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed: {e}"
                        )
            raise last_exception

        return wrapper

    return decorator
