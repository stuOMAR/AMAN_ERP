"""Unit tests for the redact_token helper added in audit PR 1.

Closes the audit's secret-leak family (F-NEW-001..004 prerequisite). These
tests run with no DB and no fixtures — pure-Python contract checks.
"""
from __future__ import annotations

import pytest

from utils.masking import redact_token, mask_pii


class TestRedactToken:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, "<empty>"),
            ("", "<empty>"),
            ("abc", "****"),
            ("abcd", "****"),
            ("abcde", "abcd\u2026****"),
            ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc", "eyJh\u2026****"),
        ],
    )
    def test_basic_cases(self, value, expected):
        assert redact_token(value) == expected

    def test_custom_head_length(self):
        assert redact_token("abcdef", head=2) == "ab\u2026****"
        assert redact_token("abcdef", head=6) == "****"  # whole string masked

    def test_never_echoes_suffix(self):
        secret = "BEGIN-RSA-PRIVATE-KEY-aSekretValue-END"
        out = redact_token(secret)
        assert "aSekretValue" not in out
        assert "PRIVATE" not in out  # whole tail must be hidden
        assert "END" not in out

    def test_non_string_input_is_coerced(self):
        # ints / UUID-like objects must not raise.
        assert redact_token(123456) == "1234\u2026****"

    def test_distinct_from_mask_pii(self):
        # mask_pii keeps the *last* N chars; redact_token keeps the *first* N.
        v = "1234567890"
        assert mask_pii(v, visible_chars=4) == "******7890"
        assert redact_token(v, head=4) == "1234\u2026****"
