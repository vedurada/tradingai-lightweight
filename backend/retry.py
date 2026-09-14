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
    TimeoutError,
)


def is_retryable(exception):
    return isinstance(exception, RETRYABLE_EXCEPTIONS)


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
