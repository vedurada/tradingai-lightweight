import time
import functools

MAX_RETRIES = 3
BASE_DELAY = 2.0
MAX_DELAY = 8.0
MAX_TOTAL_DURATION = 15.0

RETRYABLE_EXCEPTIONS = (
    OSError,
    ConnectionError,
    TimeoutError,
)

NON_RETRYABLE_HTTP_CODES = {400, 401, 403, 404, 429, 500}


def is_retryable(exception):
    if isinstance(exception, RETRYABLE_EXCEPTIONS):
        return True
    status_code = getattr(exception, "response", None)
    if status_code is not None and hasattr(status_code, "status_code"):
        return status_code.status_code not in NON_RETRYABLE_HTTP_CODES and status_code.status_code >= 500
    return False


def retry_with_backoff(max_retries=MAX_RETRIES, base_delay=BASE_DELAY, max_delay=MAX_DELAY, max_total_duration=MAX_TOTAL_DURATION):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            total_elapsed = 0.0
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt >= max_retries - 1:
                        break
                    if not is_retryable(e):
                        raise
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    if total_elapsed + delay > max_total_duration:
                        raise
                    time.sleep(delay)
                    total_elapsed += delay
            raise last_exception
        return wrapper
    return decorator
