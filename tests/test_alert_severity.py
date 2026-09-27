from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from alert_severity import (ALERTING_STATES, EXPIRED_MAX_AGE_S, SEVERITY_ORDER,
                            Thresholds, severity_for, thresholds_from,
                            worst_severity)
from monitor_config import AlertSettings
from session_state import PERM_MARKER_MAX_AGE_S


DEFAULT_THRESHOLDS = Thresholds(warning_after_s=90, critical_after_s=300)


class SeverityForMatrixTests(unittest.TestCase):
    """Table-driven pass over the severity decision matrix from DEFINE."""

    CASES = [
        ("perm", 10, True, None, "none"),
        ("perm", 90, True, None, "warning"),
        ("perm", 120, True, None, "warning"),
        ("perm", 300, True, None, "critical"),
        ("perm", 400, True, None, "critical"),
        ("ask", 400, True, None, "critical"),
        ("ask", 400, False, None, "warning"),
        ("perm", 400, False, None, "warning"),
        ("perm", 400, True, 700.0, "expired"),
        ("perm", 400, True, 1500.0, "none"),
        ("work", 9999, True, None, "none"),
        ("free", 9999, True, None, "none"),
    ]

    def test_matrix(self):
        for state, elapsed, structured, marker, expected in self.CASES:
            with self.subTest(state=state, elapsed=elapsed, structured=structured,
                              marker=marker):
                result = severity_for(
                    state, elapsed, structured=structured,
                    perm_marker_age_s=marker, thresholds=DEFAULT_THRESHOLDS)
                self.assertEqual(expected, result)


class SeverityForBoundaryTests(unittest.TestCase):
    def test_elapsed_equal_to_warning_threshold_already_warns(self):
        """The comparison is `<`, so a boundary bug that used `<=` would silently
        delay the toast by exactly one poll cycle."""
        result = severity_for(
            "perm", DEFAULT_THRESHOLDS.warning_after_s, structured=True,
            perm_marker_age_s=None, thresholds=DEFAULT_THRESHOLDS)
        self.assertEqual("warning", result)

    def test_elapsed_equal_to_critical_threshold_already_escalates(self):
        """Same boundary rule for critical: an off-by-one here means the operator
        waits one extra cycle for the loudest signal."""
        result = severity_for(
            "perm", DEFAULT_THRESHOLDS.critical_after_s, structured=True,
            perm_marker_age_s=None, thresholds=DEFAULT_THRESHOLDS)
        self.assertEqual("critical", result)

    def test_marker_age_exactly_at_max_is_not_expired(self):
        """The guard is `>`, so a marker exactly PERM_MARKER_MAX_AGE_S old must
        still be trusted -- flipping to `>=` would expire a fresh marker."""
        result = severity_for(
            "perm", 400, structured=True,
            perm_marker_age_s=PERM_MARKER_MAX_AGE_S, thresholds=DEFAULT_THRESHOLDS)
        self.assertNotEqual("expired", result)

    def test_marker_age_just_past_max_is_expired(self):
        """One tenth of a second past PERM_MARKER_MAX_AGE_S must already tip into
        `expired`, or a genuinely orphaned marker would still read as a live perm."""
        result = severity_for(
            "perm", 400, structured=True,
            perm_marker_age_s=PERM_MARKER_MAX_AGE_S + 0.1, thresholds=DEFAULT_THRESHOLDS)
        self.assertEqual("expired", result)

    def test_marker_age_exactly_at_expired_max_is_still_expired(self):
        """EXPIRED_MAX_AGE_S is an inclusive ceiling (`<=`); losing that inclusivity
        would make the panel silently fall back to `none` one instant too early."""
        result = severity_for(
            "perm", 400, structured=True,
            perm_marker_age_s=EXPIRED_MAX_AGE_S, thresholds=DEFAULT_THRESHOLDS)
        self.assertEqual("expired", result)

    def test_marker_age_just_past_expired_max_becomes_none(self):
        """Past EXPIRED_MAX_AGE_S the evidence is dead; an eternal `expired` badge
        would be as wrong as an eternal `perm` badge."""
        result = severity_for(
            "perm", 400, structured=True,
            perm_marker_age_s=EXPIRED_MAX_AGE_S + 0.1, thresholds=DEFAULT_THRESHOLDS)
        self.assertEqual("none", result)


class SeverityForProvenanceCeilingTests(unittest.TestCase):
    def test_unstructured_state_never_reaches_critical(self):
        """This is the guard against a false toast fired from an inferred state
        with no hook behind it -- unstructured must cap at `warning` for every
        elapsed value, not just the ones near the threshold."""
        for elapsed in (0, 1, 89, 90, 299, 300, 301, 9999):
            with self.subTest(elapsed=elapsed):
                result = severity_for(
                    "perm", elapsed, structured=False,
                    perm_marker_age_s=None, thresholds=DEFAULT_THRESHOLDS)
                self.assertNotEqual("critical", result)


class WorstSeverityTests(unittest.TestCase):
    def test_empty_iterable_is_none(self):
        """An empty session list must not crash the aggregate log line."""
        self.assertEqual("none", worst_severity([]))

    def test_ranking_order_matches_severity_order(self):
        """The ranking must follow SEVERITY_ORDER exactly, or a regression could
        make a merely `warning` session outrank a `critical` one in the log."""
        self.assertEqual("warning", worst_severity(["none", "warning"]))
        self.assertEqual("expired", worst_severity(["warning", "expired"]))
        self.assertEqual("critical", worst_severity(["expired", "critical"]))

    def test_critical_beats_expired_by_design(self):
        """A live blocking signal must always outrank an admission of ignorance --
        this is the specific design call from alert_severity's module docstring,
        not an incidental ordering."""
        self.assertEqual("critical", worst_severity(["critical", "expired"]))
        self.assertEqual("critical", worst_severity(["expired", "critical", "expired"]))


class WorstSeverityFailSafeTests(unittest.TestCase):
    def test_unknown_severity_in_iterable_does_not_raise(self):
        """`max(..., key=SEVERITY_ORDER.index)` without the guard would raise
        ValueError on any typo or future vocabulary drift, taking the daemon
        down with it."""
        result = worst_severity(["warning", "totally-unknown"])
        self.assertEqual("warning", result)

    def test_only_unknown_severities_fall_back_to_none(self):
        """A list made entirely of garbage values must degrade to `none`, the
        most neutral outcome, instead of raising or picking arbitrarily."""
        self.assertEqual("none", worst_severity(["bogus", "also-bogus"]))


class ThresholdsFromTests(unittest.TestCase):
    def test_converts_real_alert_settings(self):
        """thresholds_from must track AlertSettings' actual field names; using the
        real dataclass here (not a stub) catches a rename in monitor_config that a
        hand-rolled fake would silently paper over."""
        alerts = AlertSettings(warning_after_s=45, critical_after_s=180, snooze_minutes=5)
        result = thresholds_from(alerts)
        self.assertEqual(Thresholds(warning_after_s=45, critical_after_s=180), result)


class SeverityOrderContractTests(unittest.TestCase):
    def test_alerting_states_are_ask_and_perm_only(self):
        self.assertEqual(frozenset({"ask", "perm"}), ALERTING_STATES)

    def test_severity_order_is_the_documented_sequence(self):
        self.assertEqual(("none", "warning", "expired", "critical"), SEVERITY_ORDER)


if __name__ == "__main__":
    unittest.main()
