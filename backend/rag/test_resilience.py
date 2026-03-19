from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from rag.services.resilience import (
    CircuitOpenError,
    TransientExternalError,
    _circuits,
    call_with_resilience,
)


class ResilienceTests(SimpleTestCase):
    def tearDown(self):
        _circuits.clear()

    @override_settings(
        EXTERNAL_API_RETRIES=3,
        EXTERNAL_API_RETRY_BACKOFF_SECONDS=0,
        EXTERNAL_API_CIRCUIT_FAILURE_THRESHOLD=5,
        EXTERNAL_API_CIRCUIT_OPEN_SECONDS=60,
    )
    @patch("rag.services.resilience.time.sleep")
    def test_retries_then_succeeds(self, _mock_sleep):
        attempts = {"n": 0}

        def flaky_call():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise TransientExternalError("temporary")
            return {"ok": True}

        result = call_with_resilience(
            provider="semanticscholar",
            operation="search",
            func=flaky_call,
            retry_exceptions=(TransientExternalError,),
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(attempts["n"], 3)

    @override_settings(
        EXTERNAL_API_RETRIES=1,
        EXTERNAL_API_RETRY_BACKOFF_SECONDS=0,
        EXTERNAL_API_CIRCUIT_FAILURE_THRESHOLD=2,
        EXTERNAL_API_CIRCUIT_OPEN_SECONDS=60,
    )
    def test_circuit_opens_after_threshold_failures(self):
        attempts = {"n": 0}

        def always_fail():
            attempts["n"] += 1
            raise TransientExternalError("downstream failure")

        with self.assertRaises(TransientExternalError):
            call_with_resilience(
                provider="pubmed",
                operation="search",
                func=always_fail,
                retry_exceptions=(TransientExternalError,),
            )
        with self.assertRaises(TransientExternalError):
            call_with_resilience(
                provider="pubmed",
                operation="search",
                func=always_fail,
                retry_exceptions=(TransientExternalError,),
            )

        with self.assertRaises(CircuitOpenError):
            call_with_resilience(
                provider="pubmed",
                operation="search",
                func=always_fail,
                retry_exceptions=(TransientExternalError,),
            )

        # Third call must be blocked by breaker, so no extra downstream attempt.
        self.assertEqual(attempts["n"], 2)

