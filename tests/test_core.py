# ==============================================================================
# TEST SUITE: CORE UNIT TESTS AND ALGORITHMIC INVARIANTS (test_core.py)
# ==============================================================================
# Comprehensive unit tests verifying interval algebra, mass allocation ledgers,
# deterministic sequencing recurrence, closed-form makespan proofs, set-based
# robustness bounds, and raw Excel parsing integrity.
# ==============================================================================

from __future__ import annotations

import unittest
from decimal import Decimal
from fractions import Fraction as F
from itertools import pairwise, permutations, product
from pathlib import Path
from typing import Any

from src.analysis import descriptive, load_orders
from src.data_io import HOUR_US, US, excel_time_us, identifier, iso, quantity
from src.model import (
    grouped_sequence,
    pair_counts,
    robust_box,
    robustness_threshold,
    simulate,
    simulate_pair_matrix,
)
from src.temporal import (
    Interval,
    all_pairs,
    hour_parts,
    overlap,
    partition,
    uniform_allocation,
)

PROJECT_ROOT_DIR = Path(__file__).resolve().parents[1]


# ==============================================================================
# SECTION 1: SYNTHETIC TEST FIXTURES
# ==============================================================================

def make_test_jobs() -> list[dict[str, Any]]:
    """
    Construct a synthetic three-job fixture for deterministic sequence testing.

    Returns:
        List of job specification dictionaries with distinct tooling families.
    """
    return [
        {
            'order_id': order_id,
            'alias': order_id,
            'product_id': order_id,
            'group': family_group,
            'production_seconds': 3600,
            'good_pieces': 10
        }
        for order_id, family_group in [('A1', 'A'), ('B1', 'B'), ('A2', 'A')]
    ]


# ==============================================================================
# SECTION 2: TEMPORAL INTERVAL AND PARTITIONING TESTS
# ==============================================================================

class TemporalTests(unittest.TestCase):
    """
    Verify continuous interval algebra, pairwise sweeps, and timeline partitions.
    """

    def test_touching_is_not_overlap(self) -> None:
        """Assert half-open intervals sharing a boundary point exhibit zero overlap."""
        self.assertEqual(overlap(Interval('A', 'M', 0, 60), Interval('B', 'M', 60, 90)), 0)

    def test_distinct_centres(self) -> None:
        """Assert intervals on different work centres have zero intersection."""
        self.assertEqual(overlap(Interval('A', 'M', 0, 60), Interval('B', 'N', 0, 60)), 0)

    def test_nested_length(self) -> None:
        """Assert complete inclusion yields the exact duration of the nested interval."""
        self.assertEqual(overlap(Interval('A', 'M', 0, 60), Interval('B', 'M', 10, 20)), 10)

    def test_nonadjacent_pair_found(self) -> None:
        """Assert sweep line detects non-adjacent concurrent intervals on the same asset."""
        candidate_intervals = [
            Interval('A', 'M', 0, 60),
            Interval('B', 'M', 10, 20),
            Interval('C', 'M', 30, 40)
        ]
        detected_pairs = {(x['order_a'], x['order_b']) for x in all_pairs(candidate_intervals)}
        self.assertEqual(detected_pairs, {('A', 'B'), ('A', 'C')})

    def test_invalid_interval_rejected(self) -> None:
        """Assert interval creation raises ValueError when end precedes start."""
        with self.assertRaises(ValueError):
            Interval('A', 'M', 20, 10)

    def test_zero_interval_allowed(self) -> None:
        """Assert degenerate zero-duration intervals do not generate positive overlaps."""
        self.assertEqual(all_pairs([Interval('A', 'M', 20, 20), Interval('B', 'M', 0, 60)]), [])

    def test_sequential_hour_no_idle(self) -> None:
        """Assert sequential contiguous intervals conserve window without false idle gaps."""
        intervals = [
            Interval('A', 'M', 0, 25 * 60 * US, 'setup'),
            Interval('B', 'M', 25 * 60 * US, HOUR_US, 'production_window')
        ]
        partition_segments = partition(intervals, 0, HOUR_US, 'M')
        self.assertEqual(sum(segment['seconds'] for segment in partition_segments), 3600)
        self.assertFalse(
            any(
                segment['state'] in {'no_recorded_activity', 'sem_atividade_registada', 'conflict', 'conflito'}
                for segment in partition_segments
            )
        )

    def test_conflict_75_not_60_sum(self) -> None:
        """Assert overlapping durations are not truncated to clock-hour bounds."""
        intervals = [
            Interval('A', 'M', 0, HOUR_US),
            Interval('B', 'M', 30 * 60 * US, 45 * 60 * US)
        ]
        partition_segments = partition(intervals, 0, HOUR_US, 'M')
        conflict_duration = sum(
            segment['seconds']
            for segment in partition_segments
            if segment['state'] in {'conflict', 'conflito'}
        )
        self.assertEqual(conflict_duration, 900)
        self.assertEqual(
            sum(segment['seconds'] * segment['n_active'] for segment in partition_segments),
            4500
        )

    def test_triple_pairs_not_union(self) -> None:
        """Assert pairwise overlaps sum individual intersections rather than union extent."""
        intervals = [
            Interval('A', 'M', 0, 60 * US),
            Interval('B', 'M', 10 * US, 50 * US),
            Interval('C', 'M', 20 * US, 40 * US)
        ]
        self.assertEqual(sum(pair['overlap_seconds'] for pair in all_pairs(intervals)), 80)
        partition_segments = partition(intervals, 0, 60 * US, 'M')
        conflict_duration = sum(
            segment['seconds']
            for segment in partition_segments
            if segment['state'] in {'conflict', 'conflito'}
        )
        self.assertEqual(conflict_duration, 40)

    def test_uncovered_time(self) -> None:
        """Assert unrecorded gaps are assigned to the unrecorded activity state."""
        partition_segments = partition([Interval('A', 'M', 20 * US, 40 * US)], 0, 60 * US, 'M')
        idle_duration = sum(
            segment['seconds']
            for segment in partition_segments
            if segment['state'] in {'no_recorded_activity', 'sem_atividade_registada'}
        )
        self.assertEqual(idle_duration, 40)

    def test_partial_hours(self) -> None:
        """Assert decomposition across clock-hour boundaries correctly aligns segments."""
        self.assertEqual(
            hour_parts(20 * 60 * US, 70 * 60 * US),
            [(0, 40 * 60 * US), (HOUR_US, 10 * 60 * US)]
        )

    def test_indeterminate_is_not_idle(self) -> None:
        """Assert divergent setup intervals remain classified as indeterminate."""
        partition_segments = partition(
            [Interval('A', 'M', 0, 60 * US, 'indeterminate_state', True)],
            0,
            60 * US,
            'M'
        )
        self.assertIn(
            partition_segments[0]['state'],
            {'indeterminate_state', 'estado_indeterminado'}
        )
        self.assertTrue(partition_segments[0]['temporal_issue'])


# ==============================================================================
# SECTION 3: MASS CONSERVATION AND UNIFORM ALLOCATION TESTS
# ==============================================================================

class AllocationTests(unittest.TestCase):
    """
    Verify exact decimal mass conservation across decomposed hourly windows.
    """

    def test_uniform_80_20(self) -> None:
        """Assert proportional allocation across two partial-hour segments."""
        allocation_parts = uniform_allocation(100, 20 * 60 * US, 70 * 60 * US)
        allocated_volumes = [item[2] for item in allocation_parts]
        self.assertEqual(allocated_volumes, [Decimal(80), Decimal(20)])

    def test_fractional_exact_conservation(self) -> None:
        """Assert prime unit volume allocation absorbs rounding residual in the terminal hour."""
        allocation_parts = uniform_allocation(7, 0, 3 * HOUR_US)
        self.assertEqual(sum(item[2] for item in allocation_parts), 7)
        self.assertEqual(allocation_parts[-1][2], Decimal('2.333333333334'))

    def test_negative_rejected(self) -> None:
        """Assert negative unit quantities raise ValueError."""
        with self.assertRaises(ValueError):
            uniform_allocation(-1, 0, HOUR_US)

    def test_no_duration_rejected(self) -> None:
        """Assert non-positive duration raises ValueError."""
        with self.assertRaises(ValueError):
            uniform_allocation(100, 0, 0)

    def test_zero_valid(self) -> None:
        """Assert zero quantity allocation evaluates to zero without error."""
        self.assertEqual(sum(item[2] for item in uniform_allocation(0, 0, HOUR_US)), 0)

    def test_large_order_conservation(self) -> None:
        """Assert mass balance closure over high production volumes and long horizons."""
        large_volume = 123456789
        allocation_parts = uniform_allocation(large_volume, 17 * US, 300 * HOUR_US)
        self.assertEqual(sum(item[2] for item in allocation_parts), large_volume)


# ==============================================================================
# SECTION 4: DETERMINISTIC MODEL AND COMBINATORIAL SEQUENCING TESTS
# ==============================================================================

class ModelTests(unittest.TestCase):
    """
    Verify single-machine recurrence, closed-form formula matching, and sequence constraints.
    """

    def test_manual_220_202(self) -> None:
        """Verify makespan contraction on the three-job manual test case."""
        fixture_jobs = make_test_jobs()
        _, metrics_h = simulate(fixture_jobs, ['A1', 'B1', 'A2'], 120, 1200, 0)
        _, metrics_g = simulate(fixture_jobs, ['A1', 'A2', 'B1'], 120, 1200, 0)
        self.assertAlmostEqual(metrics_h['completion_hours'] * 60, 220)
        self.assertAlmostEqual(metrics_g['completion_hours'] * 60, 202)

    def test_equal_setups_tie(self) -> None:
        """Assert identical setup parameters yield zero makespan difference across sequences."""
        fixture_jobs = make_test_jobs()
        _, metrics_h = simulate(fixture_jobs, ['A1', 'B1', 'A2'], 1200, 1200, 0)
        _, metrics_g = simulate(fixture_jobs, ['A1', 'A2', 'B1'], 1200, 1200, 0)
        self.assertEqual(metrics_h['completion_hours'], metrics_g['completion_hours'])

    def test_reversal(self) -> None:
        """Assert makespan reversal when intragroup setup exceeds intergroup setup."""
        fixture_jobs = make_test_jobs()
        _, metrics_h = simulate(fixture_jobs, ['A1', 'B1', 'A2'], 1500, 1200, 0)
        _, metrics_g = simulate(fixture_jobs, ['A1', 'A2', 'B1'], 1500, 1200, 0)
        time_difference_minutes = (metrics_g['completion_hours'] - metrics_h['completion_hours']) * 60
        self.assertAlmostEqual(time_difference_minutes, 5)

    def test_zero_setups(self) -> None:
        """Assert zero setup durations evaluate makespan strictly to total processing duration."""
        _, metrics = simulate(make_test_jobs(), ['A1', 'B1', 'A2'], 0, 0, 0)
        self.assertEqual(metrics['completion_hours'], 3)

    def test_repeat_identical(self) -> None:
        """Assert determinism: identical inputs produce bitwise identical outputs."""
        fixture_jobs = make_test_jobs()
        self.assertEqual(
            simulate(fixture_jobs, ['A1', 'B1', 'A2'], 123, 456, 5),
            simulate(fixture_jobs, ['A1', 'B1', 'A2'], 123, 456, 5)
        )

    def test_duplicate_sequence_rejected(self) -> None:
        """Assert duplicate order identifiers in dispatch sequence raise ValueError."""
        with self.assertRaises(ValueError):
            simulate(make_test_jobs(), ['A1', 'B1', 'B1'], 1, 2, 0)

    def test_changed_first_rejected(self) -> None:
        """Assert altering the initial anchor order raises ValueError."""
        with self.assertRaises(ValueError):
            simulate(make_test_jobs(), ['B1', 'A1', 'A2'], 1, 2, 0)

    def test_negative_setup_rejected(self) -> None:
        """Assert negative setup duration raises ValueError."""
        with self.assertRaises(ValueError):
            simulate(make_test_jobs(), ['A1', 'B1', 'A2'], -1, 2, 0)

    def test_nonfinite_rejected(self) -> None:
        """Assert NaN setup duration raises ValueError."""
        with self.assertRaises(ValueError):
            simulate(make_test_jobs(), ['A1', 'B1', 'A2'], float('nan'), 2, 0)

    def test_nonpositive_production_rejected(self) -> None:
        """Assert non-positive production duration in job record raises ValueError."""
        fixture_jobs = make_test_jobs()
        fixture_jobs[0]['production_seconds'] = 0
        with self.assertRaises(ValueError):
            simulate(fixture_jobs, ['A1', 'B1', 'A2'], 1, 2, 0)

    def test_empty_rejected(self) -> None:
        """Assert empty job collection raises ValueError."""
        with self.assertRaises(ValueError):
            simulate([], [], 1, 2, 0)

    def test_first_and_internal_order_preserved(self) -> None:
        """Assert grouped sequence preserves initial job anchor and historical priority."""
        self.assertEqual(grouped_sequence(make_test_jobs()), ['A1', 'A2', 'B1'])

    def test_blocks_one_no_reordering(self) -> None:
        """Assert block size of one enforces historical sequence without reordering."""
        self.assertEqual(grouped_sequence(make_test_jobs(), 1), ['A1', 'B1', 'A2'])

    def test_setup_reduction_20_manual(self) -> None:
        """Verify proportional setup scaling factor against exact manual calculation."""
        fixture_jobs = make_test_jobs()
        _, metrics_h = simulate(fixture_jobs, ['A1', 'B1', 'A2'], 120, 1200, 0, F(4, 5))
        _, metrics_g = simulate(fixture_jobs, ['A1', 'A2', 'B1'], 120, 1200, 0, F(4, 5))
        self.assertAlmostEqual(metrics_h['completion_hours'] * 60, 212)
        self.assertAlmostEqual(metrics_g['completion_hours'] * 60, 197.6)

    def test_group_optimal_all_small_permutations(self) -> None:
        """Assert grouped sequence achieves global minimal makespan across all permutations."""
        job_collection = [
            {
                'order_id': str(i),
                'alias': str(i),
                'product_id': str(i),
                'group': family_label,
                'production_seconds': 10,
                'good_pieces': 1
            }
            for i, family_label in enumerate('ABCABA')
        ]
        optimal_sequence = grouped_sequence(job_collection)
        _, metrics_g = simulate(job_collection, optimal_sequence, 3, 10, 7)

        permutation_makespans = []
        for candidate_perm in permutations([job['order_id'] for job in job_collection[1:]]):
            _, metrics_h = simulate(job_collection, [job_collection[0]['order_id'], *candidate_perm], 3, 10, 7)
            permutation_makespans.append(metrics_h['completion_hours'])

        self.assertEqual(metrics_g['changes'], 2)
        self.assertEqual(metrics_g['completion_hours'], min(permutation_makespans))

    def test_quantities_constant(self) -> None:
        """Assert total conforming output remains invariant across dispatch sequences."""
        self.assertEqual(
            simulate(make_test_jobs(), ['A1', 'A2', 'B1'], 120, 1200, 0)[1]['good_pieces'],
            30
        )

    def test_single_job_initial(self) -> None:
        """Assert single job simulation correctly evaluates boundary setup and processing."""
        single_job = make_test_jobs()[:1]
        _, metrics = simulate(single_job, ['A1'], 120, 1200, 60)
        self.assertEqual(metrics['changes'], 0)
        self.assertAlmostEqual(metrics['completion_hours'] * 60, 61)


# ==============================================================================
# SECTION 5: SET-BASED ROBUSTNESS AND UNCERTAINTY BOX TESTS
# ==============================================================================

class RobustTests(unittest.TestCase):
    """
    Verify perturbation box evaluation, analytical extrema, and critical thresholds.
    """

    def test_zero_width_recovers_nominal(self) -> None:
        """Assert zero perturbation radius collapses bounds to nominal difference."""
        uncertainty_box = robust_box(
            make_test_jobs(),
            ['A1', 'B1', 'A2'],
            ['A1', 'A2', 'B1'],
            120,
            1200,
            0
        )
        self.assertEqual(uncertainty_box['lower_seconds'], 1080)
        self.assertEqual(uncertainty_box['upper_seconds'], 1080)

    def test_box_corners_exact(self) -> None:
        """Assert analytical lower and upper bounds match full combinatorial corner enumeration."""
        fixture_jobs = make_test_jobs()
        seq_h = ['A1', 'B1', 'A2']
        seq_g = ['A1', 'A2', 'B1']
        uncertainty_box = robust_box(fixture_jobs, seq_h, seq_g, 120, 1200, 180)

        edge_details = uncertainty_box['details']
        enumerated_corner_values = []

        for corner_choices in product([0, 1], repeat=len(edge_details)):
            corner_evaluation = sum(
                detail['coefficient'] * (detail['lower_seconds'] if choice == 0 else detail['upper_seconds'])
                for detail, choice in zip(edge_details, corner_choices)
            )
            enumerated_corner_values.append(corner_evaluation)

        self.assertEqual(float(uncertainty_box['lower_seconds']), min(enumerated_corner_values))
        self.assertEqual(float(uncertainty_box['upper_seconds']), max(enumerated_corner_values))

    def test_same_sequence_cancels_shared_errors(self) -> None:
        """Assert comparing identical sequences yields zero difference across all box radii."""
        uncertainty_box = robust_box(
            make_test_jobs(),
            ['A1', 'B1', 'A2'],
            ['A1', 'B1', 'A2'],
            120,
            1200,
            1000
        )
        self.assertEqual(uncertainty_box['lower_seconds'], 0)
        self.assertEqual(uncertainty_box['upper_seconds'], 0)

    def test_radius_root(self) -> None:
        """Assert critical threshold epsilon_star evaluates exactly to zero lower bound."""
        fixture_jobs = make_test_jobs()
        seq_h = ['A1', 'B1', 'A2']
        seq_g = ['A1', 'A2', 'B1']
        critical_radius = robustness_threshold(fixture_jobs, seq_h, seq_g, 120, 1200)

        self.assertIsNotNone(critical_radius)
        self.assertEqual(
            robust_box(fixture_jobs, seq_h, seq_g, 120, 1200, critical_radius)['lower_seconds'],
            0
        )
        self.assertGreater(
            robust_box(fixture_jobs, seq_h, seq_g, 120, 1200, critical_radius / 2)['lower_seconds'],
            0
        )

    def test_witness_simulated(self) -> None:
        """Assert simulation under adversarial witness matrix reproduces theoretical lower bound."""
        fixture_jobs = make_test_jobs()
        seq_h = ['A1', 'B1', 'A2']
        seq_g = ['A1', 'A2', 'B1']
        uncertainty_box = robust_box(fixture_jobs, seq_h, seq_g, 120, 1200, 900)

        witness_setup_matrix = {
            (record['predecessor_product'], record['successor_product']): record['setup_for_min_difference']
            for record in uncertainty_box['details']
        }
        witness_schedule_h = simulate_pair_matrix(fixture_jobs, seq_h, witness_setup_matrix, 0)
        witness_schedule_g = simulate_pair_matrix(fixture_jobs, seq_g, witness_setup_matrix, 0)

        makespan_delta = (
            witness_schedule_h[-1]['completion_seconds'] - witness_schedule_g[-1]['completion_seconds']
        )
        self.assertAlmostEqual(makespan_delta, float(uncertainty_box['lower_seconds']))

    def test_negative_epsilon_rejected(self) -> None:
        """Assert negative perturbation radius raises ValueError."""
        with self.assertRaises(ValueError):
            robust_box(make_test_jobs(), ['A1', 'B1', 'A2'], ['A1', 'A2', 'B1'], 120, 1200, -1)


# ==============================================================================
# SECTION 6: RAW TRANSACTIONAL INGESTION AND QUALITY AUDIT TESTS
# ==============================================================================

class InputTests(unittest.TestCase):
    """
    Verify low-level ingestion, timestamp serialization, and data quality indicators.
    """

    @classmethod
    def setUpClass(cls) -> None:
        """Load and audit master production order workbook."""
        raw_rows, orders, precision_audit = load_orders(
            PROJECT_ROOT_DIR / 'input' / 'production_order.xlsx'
        )
        cls.raw = raw_rows
        cls.orders = orders
        cls.precision = precision_audit

    def test_source_shape(self) -> None:
        """Assert fleet-wide order row count is exactly 2,751."""
        self.assertEqual(len(self.orders), 2751)

    def test_quantities_source(self) -> None:
        """Assert total completed conforming unit volume matches raw input sum."""
        self.assertEqual(sum(record['completed_quantity'] for record in self.orders), 678036228)

    def test_three_missing_times(self) -> None:
        """Assert exactly 3 transactional records exhibit missing timestamp attributes."""
        self.assertEqual(sum(record['flag_missing_time'] for record in self.orders), 3)

    def test_sixteen_divergences(self) -> None:
        """Assert exactly 16 records exhibit divergent setup initiation timestamps."""
        self.assertEqual(sum(record['flag_timestamp_divergence'] for record in self.orders), 16)

    def test_negative_quantities_retained(self) -> None:
        """Assert negative scrap records and negative conforming adjustments are retained."""
        self.assertEqual(sum(record['flag_negative_scrap'] for record in self.orders), 368)
        negative_good_volume = sum(
            record['completed_quantity']
            for record in self.orders
            if record['flag_negative_good']
        )
        self.assertEqual(negative_good_volume, -45)

    def test_missing_marker(self) -> None:
        """Assert period marker string token is parsed as missing timestamp."""
        self.assertIsNone(excel_time_us('.')[0])

    def test_datetime_first(self) -> None:
        """Assert serial date conversion correctly aligns to integer second epoch."""
        parsed_epoch_us, _ = excel_time_us('45993.505104166667')
        self.assertEqual(iso(parsed_epoch_us), '2025-12-02 12:07:21')

    def test_microsecond_precision_not_minutes(self) -> None:
        """Assert serialization correction is confined strictly within one microsecond."""
        max_correction = max(
            abs(Decimal(record['serialization_correction_seconds']))
            for record in self.precision
        )
        self.assertLess(max_correction, Decimal('0.000001'))

    def test_fractional_quantity_rejected(self) -> None:
        """Assert fractional unit volume raises ValueError."""
        with self.assertRaises(ValueError):
            quantity('3.2')

    def test_text_id_preserved(self) -> None:
        """Assert textual identifier normalizer preserves leading zeroes."""
        self.assertEqual(identifier('00123'), '00123')

    def test_sd_one_missing(self) -> None:
        """Assert standard deviation of a single-element sample evaluates to None."""
        self.assertIsNone(descriptive([173])['sd'])

    def test_overplan_not_clipped(self) -> None:
        """Assert plan attainment is not artificially capped at 100 percent."""
        overplan_records = [
            record for record in self.orders
            if record['completed_quantity'] > record['planned_quantity'] > 0
        ]
        self.assertTrue(overplan_records)
        self.assertTrue(all(record['plan_attainment'] > 1 for record in overplan_records))

    def test_negative_scrap_yield_missing(self) -> None:
        """Assert process yield is marked uncomputable when scrap is negative."""
        self.assertTrue(
            all(record['yield'] is None for record in self.orders if record['flag_negative_scrap'])
        )


# ==============================================================================
# SECTION 7: TEST RUNNER INVOCATION
# ==============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)