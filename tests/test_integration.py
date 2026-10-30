# ==============================================================================
# TEST SUITE: INTEGRATION AND REGRESSION VERIFICATION (test_integration.py)
# ==============================================================================
# Verifies end-to-end analytical pipeline invariants, mass conservation ledgers,
# non-overlapping resource allocations, and mathematical benchmark properties
# across materialized CSV and JSON output artifacts.
# ==============================================================================

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import unittest

from src.data_io import read_csv

# ==============================================================================
# SECTION 1: ARTIFACT LOCATION RESOLUTION
# ==============================================================================

PROJECT_ROOT_DIR = Path(__file__).resolve().parents[1]
RESULTS_OUTPUT_DIR = Path(
    os.environ.get(
        'LR3_RESULTS',
        os.environ.get('BENCHMARK_RESULTS', PROJECT_ROOT_DIR / 'results')
    )
).resolve()


# ==============================================================================
# SECTION 2: INTEGRATION TEST SUITE IMPLEMENTATION
# ==============================================================================

class IntegrationTests(unittest.TestCase):
    """
    Integration tests asserting structural and algebraic invariants on calculated files.
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        Verify that summary.json exists before executing integration assertions.
        Fails explicitly if artifacts are missing, ensuring zero skipped tests.
        """
        summary_path = RESULTS_OUTPUT_DIR / 'summary.json'
        if not summary_path.exists():
            raise FileNotFoundError(
                f'Required benchmark artifact missing: {summary_path}. '
                'Set the LR3_RESULTS environment variable to the results directory or run the generation pipeline.'
            )
        cls.summary = json.loads(summary_path.read_text(encoding='utf-8'))

    def test_primary_sample(self) -> None:
        """Assert cohort dimensions and isolation of quarantined order LR3_074."""
        self.assertEqual(self.summary['lr3_primary_n'], 78)
        self.assertEqual(self.summary['lr3_all_n'], 79)
        self.assertEqual(self.summary['lr3_exclusions'][0]['alias'], 'LR3_074')

    def test_no_new_adjacency_in_calibration(self) -> None:
        """Verify that order exclusion does not create synthetic empirical transitions."""
        transition_rows = read_csv(RESULTS_OUTPUT_DIR / 'lr3_original_transitions.csv')
        self.assertEqual(len(transition_rows), 78)
        self.assertEqual(sum(row['both_primary'] == 'True' for row in transition_rows), 76)
        self.assertEqual(self.summary['reference_inter_n'], 75)
        self.assertEqual(self.summary['reference_intra_n'], 1)

    def test_two_start_definitions_reported(self) -> None:
        """Verify pairwise concurrency counts under both setup initiation conventions."""
        self.assertEqual(self.summary['overlap_pairs_changeover'], 254)
        self.assertEqual(self.summary['overlap_pairs_actual'], 255)

    def test_no_false_approval(self) -> None:
        """Ensure programmatic audit flags register failures and unvalidated dimensions."""
        status_rows = read_csv(RESULTS_OUTPUT_DIR / 'validation_status.csv')
        verification_statuses = {row['check']: row['status'] for row in status_rows}

        global_capacity_status = verification_statuses.get(
            'global_data_capacity',
            verification_statuses.get('capacidade_dados_globais')
        )
        self.assertIn(global_capacity_status, {'FAILED', 'REPROVADO'})

        independent_validation_status = verification_statuses.get(
            'independent_operational_validation',
            verification_statuses.get('validacao_operacional_independente')
        )
        self.assertIn(independent_validation_status, {'NOT_EVALUATED', 'NAO_AVALIADO'})

        lr3_sample_status = verification_statuses.get(
            'lr3_sample_capacity',
            verification_statuses.get('capacidade_amostra_LR3')
        )
        self.assertIn(lr3_sample_status, {'PASSED', 'APROVADO'})

    def test_written_hourly_partition(self) -> None:
        """Verify disjoint hour partition duration conservation in resource_hourly.csv.gz."""
        hourly_rows = read_csv(RESULTS_OUTPUT_DIR / 'resource_hourly.csv.gz')
        for record in hourly_rows:
            allocated_minutes_sum = sum(
                float(record[metric_col])
                for metric_col in [
                    'setup_minutes',
                    'production_window_minutes',
                    'indeterminate_minutes',
                    'conflict_minutes',
                    'no_registered_activity_minutes'
                ]
            )
            self.assertAlmostEqual(allocated_minutes_sum, float(record['window_minutes']), places=8)
            self.assertLessEqual(float(record['window_minutes']), 60.0)

    def test_written_quantities_by_order(self) -> None:
        """Verify mass balance closure and non-negative piece allocations."""
        accumulated_allocations: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)

        for allocation_record in read_csv(RESULTS_OUTPUT_DIR / 'order_hour_allocations.csv.gz'):
            self.assertGreater(float(allocation_record['production_intersection_seconds']), 0.0)
            self.assertGreaterEqual(Decimal(allocation_record['allocated_pieces']), 0)
            order_stream_key = (allocation_record['order_id'], allocation_record['quantity_field'])
            accumulated_allocations[order_stream_key] += Decimal(allocation_record['allocated_pieces'])

        for ledger_record in read_csv(RESULTS_OUTPUT_DIR / 'quantity_ledger.csv'):
            order_stream_key = (ledger_record['order_id'], ledger_record['quantity_field'])
            self.assertEqual(
                accumulated_allocations[order_stream_key],
                Decimal(ledger_record['allocated_pieces'])
            )

            expected_balance = (
                Decimal(ledger_record['allocated_pieces'])
                + Decimal(ledger_record['unallocated_nonnegative'])
                + Decimal(ledger_record['signed_adjustment'])
            )
            self.assertEqual(Decimal(ledger_record['source_signed']), expected_balance)

    def test_written_scenarios_same_jobs(self) -> None:
        """Verify order preservation and non-preemptive execution across all benchmark scenarios."""
        unique_order_sets = []
        conforming_totals = []

        for scenario_tag in ['H0', 'G0', 'H20', 'G20']:
            schedule_records = read_csv(RESULTS_OUTPUT_DIR / f'schedule_{scenario_tag}.csv')
            unique_order_sets.append({record['order_id'] for record in schedule_records})
            conforming_totals.append(sum(int(record['good_pieces']) for record in schedule_records))

            self.assertEqual(len(schedule_records), 78)
            self.assertEqual(schedule_records[0]['alias'], 'LR3_001')

            previous_completion = 0.0
            for record in schedule_records:
                self.assertAlmostEqual(float(record['setup_start_seconds']), previous_completion, places=7)
                previous_completion = float(record['completion_seconds'])

        self.assertTrue(all(order_set == unique_order_sets[0] for order_set in unique_order_sets))
        self.assertEqual(set(conforming_totals), {79394144})

    def test_nominal_result_and_analytical(self) -> None:
        """Verify makespan contraction against the exact algebraic closed form 52(b - a)."""
        setup_a = self.summary['reference_a_minutes']
        setup_b = self.summary['reference_b_minutes']
        expected_saving_hours = 52 * (setup_b - setup_a) / 60

        self.assertAlmostEqual(self.summary['reference_saving_hours'], expected_saving_hours, places=9)
        self.assertAlmostEqual(self.summary['reference_saving_percent'], 1.1101483433689467, places=9)

    def test_ratio_one_ties(self) -> None:
        """Assert that identical setup durations yield zero makespan difference."""
        ratio_one_records = [
            row for row in read_csv(RESULTS_OUTPUT_DIR / 'sensitivity_grid.csv')
            if float(row['a_over_b']) == 1.0
        ]
        self.assertTrue(ratio_one_records)
        self.assertTrue(all(abs(float(row['saving_hours'])) < 1e-9 for row in ratio_one_records))

    def test_radius_is_zero_not_probability(self) -> None:
        """Verify critical perturbation radius epsilon_star where lower saving boundary reaches zero."""
        robustness_records = read_csv(RESULTS_OUTPUT_DIR / 'robust_pair_uncertainty.csv')
        critical_point = min(
            robustness_records,
            key=lambda row: abs(float(row['epsilon_minutes']) - self.summary['robust_critical_epsilon_minutes'])
        )
        self.assertAlmostEqual(float(critical_point['minimum_saving_hours']), 0.0, places=10)
        self.assertEqual(critical_point['strictly_positive_for_all_setups_in_box'], 'False')

    def test_constructed_witness_reversal(self) -> None:
        """Assert that the adversarial witness schedule reproduces the theoretical lower bound."""
        schedule_h = read_csv(RESULTS_OUTPUT_DIR / 'robust_witness_schedule_H.csv')
        schedule_g = read_csv(RESULTS_OUTPUT_DIR / 'robust_witness_schedule_G.csv')
        makespan_delta_hours = (
            float(schedule_h[-1]['completion_seconds']) - float(schedule_g[-1]['completion_seconds'])
        ) / 3600
        self.assertAlmostEqual(makespan_delta_hours, -13.371777777777778, places=8)

    def test_catalog_not_physical_validation(self) -> None:
        """Audit master catalog coverage without inferring unvalidated physical setup equivalence."""
        catalog_audit = self.summary['product_detail_audit']
        self.assertEqual(catalog_audit['lr3_products_matched'], 24)
        self.assertEqual(catalog_audit['duplicate_product_attribute_keys'], 0)
        self.assertFalse(catalog_audit['simulation_uses_productdetail_values'])

    def test_completed_order_shifts(self) -> None:
        """Verify completion time displacement counts along the reordered schedule."""
        self.assertEqual(self.summary['completion_later_orders'], 37)
        self.assertEqual(self.summary['completion_earlier_orders'], 40)

    def test_schema_conservation_and_counts(self) -> None:
        """Assert fleet-wide order row conservation and reference changeover reduction."""
        self.assertEqual(len(read_csv(RESULTS_OUTPUT_DIR / 'orders_audited.csv')), 2751)
        self.assertEqual(self.summary['reference_delta_changes'], 52)


# ==============================================================================
# SECTION 3: TEST RUNNER INVOCATION
# ==============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)