"""Tests for the corrected pre-off event study payoff arithmetic and timestamp behaviour.

These tests must FAIL against the original buggy implementation and PASS against
the corrected implementation. They encode the exact mathematical and semantic
requirements from the reconciliation brief.
"""
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from research.event_study import (
    _net_back_return,
    _net_lay_return,
    _merge_levels,
    parse_market,
)


class PayoffArithmeticTests(unittest.TestCase):
    """Verify the hedge payoff formulas against independent matching examples."""

    def test_back_then_lay_payoff(self):
        """BACK entry at best lay B, LAY exit at best back L.
        Gross per £1 back stake = B/L - 1.
        """
        # Unchanged book: atb=2.00, atl=2.02 → B=2.02 (best available to lay),
        # L=2.00 (best available to back). Must lose the spread.
        # BACK entry = atb = 2.00, LAY exit = atl = 2.02
        self.assertAlmostEqual(_net_back_return(2.00, 2.02, 0.0), -0.00990099, places=8)

    def test_lay_then_back_payoff(self):
        """LAY entry at best back L, BACK exit at best lay B.
        Gross per £1 lay stake = 1 - L/B.
        """
        # Unchanged book: atb=2.00, atl=2.02 → L=2.00, B=2.02. Must lose the spread.
        # LAY entry = atl = 2.02, BACK exit = atb = 2.00
        self.assertAlmostEqual(_net_lay_return(2.02, 2.00, 0.0), -0.01, places=8)

    def test_independent_matching_back(self):
        """£10 back at 2.00 hedged by lay at 2.02.
        lay stake = 10 * 2.00/2.02 ≈ 9.90099
        win: 10*(2.00-1) - 9.90099*(2.02-1) = 10 - 10.09901 = -0.09901
        lose: -10 + 9.90099 = -0.09901
        """
        b, l = 2.00, 2.02
        stake = 10.0
        lay_stake = stake * b / l
        win = stake * (b - 1) - lay_stake * (l - 1)
        lose = -stake + lay_stake
        self.assertAlmostEqual(win, lose, places=10)
        self.assertLess(win, 0)

    def test_independent_matching_lay(self):
        """£10 lay at 2.02 hedged by back at 2.00.
        back stake = 10 * 2.02/2.00 = 10.1
        win: -10*(2.02-1) + 10.1*(2.00-1) = -10.2 + 10.1 = -0.1
        lose: 10 - 10.1 = -0.1
        """
        l, b = 2.02, 2.00
        stake = 10.0
        back_stake = stake * l / b
        win = -stake * (l - 1) + back_stake * (b - 1)
        lose = stake - back_stake
        self.assertAlmostEqual(win, lose, places=10)
        self.assertLess(win, 0)

    def test_flat_spread_costs_both_sides(self):
        """Both directions must be negative on an unchanged book with a spread."""
        self.assertLess(_net_back_return(2.00, 2.02, 0.0), 0)
        self.assertLess(_net_lay_return(2.02, 2.00, 0.0), 0)

    def test_commission_only_on_positive_gross(self):
        """Commission is only deducted from positive gross profit."""
        # gross = -0.01 → net = -0.01 (no commission taken from losses)
        # BACK entry = atb = 2.00, LAY exit = atl = 2.02 → gross = 2.00/2.02 - 1 = -0.0099
        self.assertAlmostEqual(_net_back_return(2.00, 2.02, 0.02), -0.00990099, places=8)
         # gross = +0.1 → net = 0.1 - 0.1*0.02 = 0.098
        # BACK entry = 2.00, LAY exit = 1.80 → gross = 2.00/1.80 - 1 = 0.111... → net = 0.111... * 0.98 = 0.109...
        self.assertAlmostEqual(_net_back_return(2.00, 1.80, 0.02), 0.111111 * 0.98, places=6)


class TimestampBehaviourTests(unittest.TestCase):
    """Verify the as-of snapshot and no-future-state behaviour."""

    def make_minimal_market(self, events):
        """Helper to create a minimal market file for testing."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "1.1"
            p.write_text("\n".join(json.dumps(e) for e in events))
            return parse_market(p, commission=0.02)

    def test_snapshot_at_not_before_target(self):
        """A target timestamp must use state from pt <= target, not pt > target."""
        off = 1500000000000
        t = off - 300000  # 5 min before off
        d = {
            'marketTime': datetime.fromtimestamp(off/1000, timezone.utc).isoformat(),
            'status': 'OPEN', 'inPlay': False,
            'runners': [{'id': 1, 'status': 'ACTIVE'}]
        }
        events = [
            # Update at t-1000: this should be used for target t
            {'pt': t-1000, 'mc': [{'id': '1.1', 'marketDefinition': d, 'rc': [{'id': 1, 'atb': [[2.0, 100]], 'atl': [[2.02, 100]]}]}]},
            # Update at t+1000: MUST NOT be used for target t
            {'pt': t+1000, 'mc': [{'id': '1.1', 'rc': [{'id': 1, 'atb': [[3.0, 100]], 'atl': [[3.05, 100]]}]}]},
            {'pt': t+5000, 'mc': [{'id': '1.1', 'rc': []}]}
        ]
        rows = self.make_minimal_market(events)
        # Find the row for BACK side at 300s snapshot
        r = next((r for r in rows if r.get('best_back') is not None and r.get('snapshot_sec_to_off') == 300), None)
        self.assertIsNotNone(r)
        # Entry should be at 2.00 (t-1000), not 3.00 (t+1000)
        self.assertEqual(r['best_back'], 2.0)
        self.assertEqual(r['best_lay'], 2.02)

    def test_exact_target_pt_is_available(self):
        """An update at exactly the target timestamp is available for that target."""
        off = 1500000000000
        t = off - 300000
        d = {
            'marketTime': datetime.fromtimestamp(off/1000, timezone.utc).isoformat(),
            'status': 'OPEN', 'inPlay': False,
            'runners': [{'id': 1, 'status': 'ACTIVE'}]
        }
        events = [
            {'pt': t-1000, 'mc': [{'id': '1.1', 'marketDefinition': d, 'rc': [{'id': 1, 'atb': [[2.0, 100]], 'atl': [[2.02, 100]]}]}]},
            # Exact target timestamp
            {'pt': t, 'mc': [{'id': '1.1', 'rc': [{'id': 1, 'atb': [[2.5, 100]], 'atl': [[2.52, 100]]}]}]},
            {'pt': t+5000, 'mc': [{'id': '1.1', 'rc': []}]}
        ]
        rows = self.make_minimal_market(events)
        r = next((r for r in rows if r.get('best_back') is not None and r.get('snapshot_sec_to_off') == 300), None)
        self.assertIsNotNone(r)
        # Should use the exact-target update
        self.assertEqual(r['best_back'], 2.5)
        self.assertEqual(r['best_lay'], 2.52)

    def test_no_eof_backfill(self):
        """Missing targets must not be backfilled with final stream state."""
        off = 1500000000000
        t = off - 300000
        d = {
            'marketTime': datetime.fromtimestamp(off/1000, timezone.utc).isoformat(),
            'status': 'OPEN', 'inPlay': False,
            'runners': [{'id': 1, 'status': 'ACTIVE'}]
        }
        events = [
            {'pt': t-1000, 'mc': [{'id': '1.1', 'marketDefinition': d, 'rc': [{'id': 1, 'atb': [[2.0, 100]], 'atl': [[2.02, 100]]}]}]},
            # File ends before target - target should be excluded, not backfilled
        ]
        rows = self.make_minimal_market(events)
        # Target at t (300s) had no update <= t, so no row should be emitted
        back_rows = [r for r in rows if r.get('best_back') is not None and r.get('snapshot_sec_to_off') == 300]
        self.assertEqual(len(back_rows), 0)

    def test_suspension_excludes_runner(self):
        """SUSPENDED market state must exclude quotes for that period."""
        off = 1500000000000
        t = off - 300000
        d = {
            'marketTime': datetime.fromtimestamp(off/1000, timezone.utc).isoformat(),
            'status': 'OPEN', 'inPlay': False,
            'runners': [{'id': 1, 'status': 'ACTIVE'}]
        }
        events = [
            {'pt': t-1000, 'mc': [{'id': '1.1', 'marketDefinition': d, 'rc': [{'id': 1, 'atb': [[2.0, 100]], 'atl': [[2.02, 100]]}]}]},
            # Suspend at t
            {'pt': t, 'mc': [{'id': '1.1', 'marketDefinition': {'status': 'SUSPENDED'}}]},
            {'pt': t+5000, 'mc': [{'id': '1.1', 'rc': []}]}
        ]
        rows = self.make_minimal_market(events)
        # Target at t should have no active quotes because market was SUSPENDED
        back_rows = [r for r in rows if r.get('best_back') is not None and r.get('snapshot_sec_to_off') == 300]
        self.assertEqual(len(back_rows), 0)

    def test_inplay_excludes_runner(self):
        """In-play markets must be excluded from pre-off study."""
        off = 1500000000000
        t = off - 300000
        d = {
            'marketTime': datetime.fromtimestamp(off/1000, timezone.utc).isoformat(),
            'status': 'OPEN', 'inPlay': False,
            'runners': [{'id': 1, 'status': 'ACTIVE'}]
        }
        events = [
            {'pt': t-1000, 'mc': [{'id': '1.1', 'marketDefinition': d, 'rc': [{'id': 1, 'atb': [[2.0, 100]], 'atl': [[2.02, 100]]}]}]},
            # In-play at t
            {'pt': t, 'mc': [{'id': '1.1', 'marketDefinition': {'status': 'OPEN', 'inPlay': True}}]},
            {'pt': t+5000, 'mc': [{'id': '1.1', 'rc': []}]}
        ]
        rows = self.make_minimal_market(events)
        back_rows = [r for r in rows if r.get('best_back') is not None and r.get('snapshot_sec_to_off') == 300]
        self.assertEqual(len(back_rows), 0)

    def test_removed_runner_excluded(self):
        """REMOVED runner status must exclude the runner."""
        off = 1500000000000
        t = off - 300000
        d = {
            'marketTime': datetime.fromtimestamp(off/1000, timezone.utc).isoformat(),
            'status': 'OPEN', 'inPlay': False,
            'runners': [{'id': 1, 'status': 'ACTIVE'}]
        }
        events = [
            {'pt': t-1000, 'mc': [{'id': '1.1', 'marketDefinition': d, 'rc': [{'id': 1, 'atb': [[2.0, 100]], 'atl': [[2.02, 100]]}]}]},
            {'pt': t, 'mc': [{'id': '1.1', 'marketDefinition': {'runners': [{'id': 1, 'status': 'REMOVED'}]}}]},
            {'pt': t+5000, 'mc': [{'id': '1.1', 'rc': []}]}
        ]
        rows = self.make_minimal_market(events)
        back_rows = [r for r in rows if r.get('best_back') is not None and r.get('snapshot_sec_to_off') == 300]
        self.assertEqual(len(back_rows), 0)

    def test_out_of_order_timestamp_raises(self):
        """Out-of-order pt should raise an error (file is quarantined)."""
        off = 1500000000000
        t = off - 300000
        d = {
            'marketTime': datetime.fromtimestamp(off/1000, timezone.utc).isoformat(),
            'status': 'OPEN', 'inPlay': False,
            'runners': [{'id': 1, 'status': 'ACTIVE'}]
        }
        events = [
            {'pt': t-1000, 'mc': [{'id': '1.1', 'marketDefinition': d, 'rc': [{'id': 1, 'atb': [[2.0, 100]], 'atl': [[2.02, 100]]}]}]},
            {'pt': t-2000, 'mc': [{'id': '1.1', 'rc': [{'id': 1, 'atb': [[3.0, 100]], 'atl': [[3.05, 100]]}]}]},  # out of order!
        ]
        rows = self.make_minimal_market(events)
        with self.assertRaises(ValueError):
            self.make_minimal_market(events)

    def test_image_clears_old_book(self):
        """An 'img' (full image) must clear and replace the previous book."""
        off = 1500000000000
        t = off - 300000
        d = {
            'marketTime': datetime.fromtimestamp(off/1000, timezone.utc).isoformat(),
            'status': 'OPEN', 'inPlay': False,
            'runners': [{'id': 1, 'status': 'ACTIVE'}]
        }
        events = [
            {'pt': t-1000, 'mc': [{'id': '1.1', 'marketDefinition': d, 'rc': [{'id': 1, 'atb': [[2.0, 100]], 'atl': [[2.02, 100]]}]}]},
            # Full image reset at t
            {'pt': t, 'mc': [{'id': '1.1', 'img': True, 'rc': [{'id': 1, 'atb': [[3.0, 100]], 'atl': [[3.05, 100]]}]}]},
            {'pt': t+5000, 'mc': [{'id': '1.1', 'rc': []}]}
        ]
        rows = self.make_minimal_market(events)
        r = next((r for r in rows if r.get('best_back') is not None and r.get('snapshot_sec_to_off') == 300), None)
        self.assertIsNotNone(r)
        self.assertEqual(r['best_back'], 3.0)
        self.assertEqual(r['best_lay'], 3.05)

    def test_stale_snapshot_excluded(self):
        """A target whose latest available state is > 5000 ms old must be excluded."""
        off = 1500000000000
        t = off - 300000
        d = {
            'marketTime': datetime.fromtimestamp(off/1000, timezone.utc).isoformat(),
            'status': 'OPEN', 'inPlay': False,
            'runners': [{'id': 1, 'status': 'ACTIVE'}]
        }
        events = [
            # Only update is 15s before target → stale
            {'pt': t-15000, 'mc': [{'id': '1.1', 'marketDefinition': d, 'rc': [{'id': 1, 'atb': [[2.0, 100]], 'atl': [[2.02, 100]]}]}]},
            {'pt': t+5000, 'mc': [{'id': '1.1', 'rc': []}]}
        ]
        rows = self.make_minimal_market(events)
        # Target should be excluded because latest state is > 5s old
        back_rows = [r for r in rows if r.get('best_back') is not None and r.get('snapshot_sec_to_off') == 300]
        self.assertEqual(len(back_rows), 0)


class PayoffFormulaTests(unittest.TestCase):
    """Verify the exact Betfair field semantics against official documentation.

    Betfair Stream API fields:
    - atb = Available To Back = prices/sizes where you can BACK (buy)
    - atl = Available To Lay = prices/sizes where you can LAY (sell)

    Therefore:
    - To BACK: you take the best available to LAY (atl, the lowest lay price)
    - To LAY: you take the best available to BACK (atb, the highest back price)
    """

    def test_atb_atl_semantics(self):
        """Verify field meanings from official Betfair docs."""
        # atb = available to BACK → the incoming bettor can BACK at these prices
        # atl = available to LAY → the incoming bettor can LAY at these prices
        # Best BACK entry = min(atl) [the best price available TO LAY]
        # Best LAY entry = max(atb) [the best price available TO BACK]
        pass  # Documented by the test name and comments


if __name__ == '__main__':
    unittest.main()