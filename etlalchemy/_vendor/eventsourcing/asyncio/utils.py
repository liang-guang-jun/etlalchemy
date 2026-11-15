from __future__ import annotations

import asyncio
from functools import wraps
from random import random
from typing import TYPE_CHECKING, Any, no_type_check

if TYPE_CHECKING:
    from collections.abc import Callable


def async_retry(
    exc: type[Exception] | tuple[type[Exception], ...] = Exception,
    max_attempts: int = 1,
    wait: float = 0,
    stall: float = 0,
) -> Callable[[Any], Any]:
    """Retry decorator for asynchronous functions.

    :param exc: Exception(s) that will cause the call to be retried if raised.
    :param max_attempts: Maximum number of attempts to try.
    :param wait: Amount of time to wait before retrying after an exception.
    :param stall: Amount of time to wait before the first attempt.
    :return: Returns the value returned by the decorated coroutine function.
    """

    @no_type_check
    def _retry(func: Callable) -> Callable:
        @wraps(func)
        async def retry_decorator(*args: Any, **kwargs: Any) -> Any:
            if stall:
                await asyncio.sleep(stall)
            attempts = 0
            while True:
                try:
                    return await func(*args, **kwargs)
                except exc:
                    attempts += 1
                    if max_attempts is None or attempts < max_attempts:
                        await asyncio.sleep(
                            wait * (1 + 0.1 * (random() - 0.5))  # noqa: S311
                        )
                    else:
                        raise

        return retry_decorator

    if isinstance(exc, (list, tuple)):
        for _exc in exc:
            if not (isinstance(_exc, type) and issubclass(_exc, Exception)):
                msg = f"not an exception class: {_exc}"
                raise TypeError(msg)
    elif not (isinstance(exc, type) and issubclass(exc, Exception)):
        msg = f"not an exception class: {exc}"
        raise TypeError(msg)
    if not isinstance(max_attempts, int):
        msg = f"'max_attempts' must be an int: {max_attempts}"
        raise TypeError(msg)
    if not isinstance(wait, (float, int)):
        msg = f"'wait' must be a float: {max_attempts}"
        raise TypeError(msg)
    if not isinstance(stall, (float, int)):
        msg = f"'stall' must be a float: {max_attempts}"
        raise TypeError(msg)
    return _retry
