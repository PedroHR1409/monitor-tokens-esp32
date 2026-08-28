from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from usage_model import UsageSeries, combine_usage, context_measurement  # noqa: E402
from session_meta import context_usage  # noqa: E402


class UsageSeriesTests(unittest.TestCase):
    def test_claude_only_series_keeps_its_provider_label(self):
        """Relabelling Claude-only data as combined would overstate its provenance."""
        claude = UsageSeries("claude", {"2026-08-27T12:00:00Z": 120}, 120, "measured")

        self.assertEqual((claude,), combine_usage(claude))

    def test_matching_hour_buckets_combine_both_provider_totals(self):
        """Dropping either provider from aligned buckets would undercount the shared graph."""
        claude = UsageSeries("claude", {"2026-08-27T12:00:00Z": 120}, 120, "measured")
        codex = UsageSeries("codex", {"2026-08-27T12:00:00Z": 80}, 80, "measured")

        self.assertEqual((UsageSeries("claude+codex", {"2026-08-27T12:00:00Z": 200},
                                      200, "measured"),),
                         combine_usage(claude, codex))

    def test_absent_codex_data_never_claims_a_combined_provider(self):
        """Changing a Claude-only label to combined would falsely promise Codex coverage."""
        claude = UsageSeries("claude", {"2026-08-27T12:00:00Z": 120}, 120, "measured")

        output, = combine_usage(claude)

        self.assertEqual("claude", output.provider)

    def test_different_hour_periods_stay_as_separate_series(self):
        """Merging buckets with different periods would put token usage in the wrong hour."""
        claude = UsageSeries("claude", {"2026-08-27T11:00:00Z": 120}, 120, "measured")
        codex = UsageSeries("codex", {"2026-08-27T12:00:00Z": 80}, 80, "measured")

        self.assertEqual((claude, codex), combine_usage(claude, codex))


class ContextMeasurementTests(unittest.TestCase):
    def test_claude_context_without_a_limit_is_unknown_but_keeps_raw_tokens(self):
        """A fallback denominator would turn an unproven Claude percentage into a fact."""
        self.assertEqual({"tokens": 62_500, "limit": None, "pct": 0, "quality": "unknown"},
                         context_measurement(62_500))

    def test_explicitly_configured_limit_is_labelled_configured(self):
        """Treating an operator-supplied limit as measured would misstate its source."""
        self.assertEqual({"tokens": 50, "limit": 200, "pct": 25, "quality": "configured"},
                         context_measurement(50, configured_limit=200))

    def test_claude_context_usage_does_not_assume_a_one_million_limit(self):
        """Restoring the 1M fallback would send a fabricated Claude percentage downstream."""
        transcript = [{"message": {"usage": {"input_tokens": 62_500}}}]

        with patch.dict("os.environ", {"MONITOR_CLAUDE_CONTEXT_WINDOW": ""}):
            measurement = context_usage(transcript)

        self.assertEqual({"tokens": 62_500, "limit": None, "pct": 0, "quality": "unknown"},
                         measurement)


if __name__ == "__main__":
    unittest.main()
