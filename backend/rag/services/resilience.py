"""
Resilience helpers for external provider calls.

Provides:
- bounded retries with exponential backoff
- in-memory circuit breaker per provider
"""

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Tuple, Type

from django.conf import settings


class CircuitOpenError(RuntimeError):
    """Raised when a provider circuit breaker is open."""


class TransientExternalError(RuntimeError):
    """Raised for transient failures that should be retried."""


@dataclass
class CircuitState:
    failure_count: int = 0
    opened_at: float | None = None


_circuit_lock = threading.Lock()
_circuits: Dict[str, CircuitState] = {}


def _provider_settings() -> Tuple[int, float, int]:
    retries = int(getattr(settings, "EXTERNAL_API_RETRIES", 3))
    backoff = float(getattr(settings, "EXTERNAL_API_RETRY_BACKOFF_SECONDS", 1.0))
    threshold = int(getattr(settings, "EXTERNAL_API_CIRCUIT_FAILURE_THRESHOLD", 5))
    return retries, backoff, threshold


def _circuit_timeout_seconds() -> float:
    return float(getattr(settings, "EXTERNAL_API_CIRCUIT_OPEN_SECONDS", 60.0))


def _is_circuit_open(provider: str) -> bool:
    now = time.time()
    timeout = _circuit_timeout_seconds()
    with _circuit_lock:
        state = _circuits.get(provider)
        if not state or state.opened_at is None:
            return False
        if (now - state.opened_at) >= timeout:
            # Cooldown elapsed: half-open state (allow next call).
            state.opened_at = None
            state.failure_count = 0
            return False
        return True


def _record_success(provider: str) -> None:
    with _circuit_lock:
        state = _circuits.setdefault(provider, CircuitState())
        state.failure_count = 0
        state.opened_at = None


def _record_failure(provider: str) -> None:
    _, _, threshold = _provider_settings()
    with _circuit_lock:
        state = _circuits.setdefault(provider, CircuitState())
        state.failure_count += 1
        if state.failure_count >= threshold:
            state.opened_at = time.time()


def call_with_resilience(
    *,
    provider: str,
    operation: str,
    func: Callable[[], object],
    retry_exceptions: Tuple[Type[BaseException], ...],
) -> object:
    """
    Execute an external call with retry + circuit breaker.
    """
    retries, backoff_base, _ = _provider_settings()

    if _is_circuit_open(provider):
        raise CircuitOpenError(
            f"Circuit open for provider '{provider}' during '{operation}'"
        )

    last_error: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            result = func()
            _record_success(provider)
            return result
        except retry_exceptions as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(backoff_base * (2 ** (attempt - 1)))
            continue

    _record_failure(provider)
    if last_error:
        raise last_error
    raise RuntimeError(f"External call failed: {provider}/{operation}")

