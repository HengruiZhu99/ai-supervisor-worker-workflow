from __future__ import annotations

import unittest

from aiflow.api.security import RequestSecurity, SecurityError, validate_bind


class ApiSecurityTests(unittest.TestCase):
    def test_loopback_is_mandatory_even_when_legacy_remote_flag_is_present(self) -> None:
        self.assertEqual(validate_bind("127.0.0.1"), "127.0.0.1")
        self.assertEqual(validate_bind("::1"), "::1")
        with self.assertRaises(SecurityError):
            validate_bind("0.0.0.0")
        with self.assertRaises(SecurityError):
            validate_bind("0.0.0.0", allow_remote=True)

    def test_mutation_requires_matching_host_origin_token_and_json_size(self) -> None:
        security = RequestSecurity(
            token="session-secret",
            host="127.0.0.1",
            port=8765,
            max_body_bytes=128,
        )
        valid = {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "X-AIFLOW-Token": "session-secret",
            "Content-Type": "application/json",
            "Content-Length": "12",
        }
        security.authorize_mutation(valid)
        for key in ("Host", "Origin", "X-AIFLOW-Token"):
            altered = dict(valid)
            altered[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(SecurityError):
                security.authorize_mutation(altered)
        oversized = dict(valid, **{"Content-Length": "129"})
        with self.assertRaises(SecurityError):
            security.authorize_mutation(oversized)

    def test_constant_time_token_check_rejects_missing_token(self) -> None:
        security = RequestSecurity(token="secret", host="localhost", port=9000)
        with self.assertRaises(SecurityError):
            security.authorize_mutation(
                {
                    "Host": "localhost:9000",
                    "Origin": "http://localhost:9000",
                    "Content-Type": "application/json",
                    "Content-Length": "0",
                }
            )


if __name__ == "__main__":
    unittest.main()
