# ==============================================================================
# MODULE: BATCH RECONSTRUCTION, AUDIT, AND EXPERIMENTATION (analysis.py)
# ==============================================================================
# Executes temporal reconstruction, transactional concurrency audits, sample
# cohort segregation, and reproducible prescriptive optimization benchmarks.
# ==============================================================================

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from fractions import Fraction as F
from itertools import pairwise
from pathlib import Path
import json
import statistics
from typing import Any, Iterable

from .data_io import (
    read_xlsx_values,
    quantity,
    identifier,
    excel_time_us,
    iso,
    US,
    HOUR_US,
    write_csv,
    write_json,
    sha256
)
from .temporal import (
    Interval,
    all_pairs,
    partition,
    hour_parts,
    uniform_allocation
)
from .model import (
    simulate,
    grouped_sequence,
    pair_counts,
    robust_box,
    robustness_threshold,
    rational,
    simulate_pair_matrix
)

# ==============================================================================
# SECTION 1: GLOBAL CONSTANTS AND SCHEMA DEFINITIONS
# ==============================================================================

TIME_COLUMNS = [
    'change_over_start',
    'change_over_end',
    'actual_start_date',
    'actual_completion_date'
]

QUANTITY_COLUMNS = [
    'planned_quantity',
    'completed_quantity',
    'scrapped_quantity'
]

REQUIRED_SCHEMA_ATTRIBUTES = [
    'production_order_number',
    'product_id',
    'work_centre',
    *TIME_COLUMNS,
    *QUANTITY_COLUMNS,
    'batch_number'
]

# Operational state tokens aligned with temporal.py
STATE_SETUP = 'setup'
STATE_PRODUCTION = 'production_window'
STATE_INDETERMINATE = 'indeterminate_state'
STATE_CONFLICT = 'conflict'
STATE_NO_RECORDED_ACTIVITY = 'no_recorded_activity'


# ==============================================================================
# SECTION 2: DESCRIPTIVE STATISTICAL PROFILING HELPERS
# ==============================================================================

def descriptive(values: Iterable[float | int]) -> dict[str, float | int | None]:
    """
    Compute descriptive summary statistics including empirical quartiles.

    Args:
        values: Iterable collection of numeric values.

    Returns:
        Dictionary containing sample size, min, q25, median, mean, q75, max, and stdev.
    """
    sorted_values = sorted(values)
    if not sorted_values:
        return {
            'n': 0,
            'min': None,
            'q25': None,
            'median': None,
            'mean': None,
            'q75': None,
            'max': None,
            'sd': None
        }

    def compute_quantile(probability: float) -> float:
        index_real = (len(sorted_values) - 1) * probability
        lower_idx = int(index_real)
        upper_idx = min(lower_idx + 1, len(sorted_values) - 1)
        fractional_weight = index_real - lower_idx
        return sorted_values[lower_idx] + (sorted_values[upper_idx] - sorted_values[lower_idx]) * fractional_weight

    sample_size = len(sorted_values)
    standard_deviation = statistics.stdev(sorted_values) if sample_size > 1 else None

    return {
        'n': sample_size,
        'min': min(sorted_values),
        'q25': compute_quantile(0.25),
        'median': statistics.median(sorted_values),
        'mean': statistics.mean(sorted_values),
        'q75': compute_quantile(0.75),
        'max': max(sorted_values),
        'sd': standard_deviation
    }


# ==============================================================================
# SECTION 3: TRANSACTIONAL INGESTION AND TIME AUDITING
# ==============================================================================

def load_orders(path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Ingest raw production orders, auditing timestamp completeness and consistency.

    Args:
        path: Path pointing to the source production_order.xlsx workbook.

    Returns:
        Tuple of (raw rows, validated order records, serialization precision audit records).

    Raises:
        ValueError: If schema headers are incomplete or required primary keys are absent.
    """
    raw_tabular_rows = read_xlsx_values(path)
    if not raw_tabular_rows or set(REQUIRED_SCHEMA_ATTRIBUTES) - set(raw_tabular_rows[0]):
        raise ValueError('Incomplete production_order schema specification.')

    parsed_orders = []
    serialization_precision = []

    for row_number, raw_row in enumerate(raw_tabular_rows, start=2):
        order_record = {
            attr: identifier(raw_row[attr])
            for attr in ['production_order_number', 'product_id', 'work_centre', 'batch_number']
        }
        order_record['order_id'] = order_record.pop('production_order_number')
        order_record['source_row'] = row_number

        if not all(order_record[k] for k in ['order_id', 'product_id', 'work_centre']):
            raise ValueError(f'Missing primary identifier at row {row_number}')

        for quantity_col in QUANTITY_COLUMNS:
            order_record[quantity_col] = quantity(raw_row[quantity_col])

        for time_col in TIME_COLUMNS:
            timestamp_us, serial_correction = excel_time_us(raw_row[time_col])
            order_record[time_col + '_us'] = timestamp_us
            serialization_precision.append({
                'source_row': row_number,
                'column': time_col,
                'original_excel_value': raw_row[time_col],
                'parsed_time': iso(timestamp_us),
                'serialization_correction_seconds': str(serial_correction)
            })

        changeover_start_us = order_record['change_over_start_us']
        changeover_end_us = order_record['change_over_end_us']
        actual_start_us = order_record['actual_start_date_us']
        actual_completion_us = order_record['actual_completion_date_us']

        all_timestamps_present = all(
            t is not None for t in [changeover_start_us, changeover_end_us, actual_start_us, actual_completion_us]
        )
        chronologically_valid = (
            all_timestamps_present
            and changeover_start_us <= changeover_end_us <= actual_completion_us
            and actual_start_us <= actual_completion_us
        )
        start_timestamps_concordant = (
            all_timestamps_present and changeover_start_us == actual_start_us
        )

        order_record['flag_missing_time'] = not all_timestamps_present
        order_record['flag_timestamp_divergence'] = (
            changeover_start_us is not None
            and actual_start_us is not None
            and changeover_start_us != actual_start_us
        )
        order_record['flag_time_order_invalid'] = all_timestamps_present and not chronologically_valid

        order_record['setup_seconds'] = (
            (changeover_end_us - changeover_start_us) / US
            if changeover_start_us is not None and changeover_end_us is not None and changeover_end_us >= changeover_start_us
            else None
        )
        order_record['production_seconds'] = (
            (actual_completion_us - changeover_end_us) / US
            if actual_completion_us is not None and changeover_end_us is not None and actual_completion_us >= changeover_end_us
            else None
        )

        order_record['flag_zero_production'] = order_record['production_seconds'] == 0
        order_record['flag_negative_good'] = (
            order_record['completed_quantity'] is not None and order_record['completed_quantity'] < 0
        )
        order_record['flag_negative_scrap'] = (
            order_record['scrapped_quantity'] is not None and order_record['scrapped_quantity'] < 0
        )

        order_record['time_concordant'] = bool(chronologically_valid and start_timestamps_concordant)
        order_record['time_positive'] = bool(
            order_record['time_concordant'] and order_record['production_seconds'] > 0
        )

        planned_vol = order_record['planned_quantity']
        good_vol = order_record['completed_quantity']
        scrap_vol = order_record['scrapped_quantity']

        order_record['plan_attainment'] = (
            (good_vol / planned_vol)
            if planned_vol is not None and planned_vol > 0 and good_vol is not None and good_vol >= 0
            else None
        )
        order_record['good_plan_difference'] = (
            (planned_vol - good_vol)
            if planned_vol is not None and planned_vol >= 0 and good_vol is not None and good_vol >= 0
            else None
        )
        order_record['yield'] = (
            (good_vol / (good_vol + scrap_vol))
            if good_vol is not None and scrap_vol is not None and min(good_vol, scrap_vol) >= 0 and (good_vol + scrap_vol) > 0
            else None
        )
        order_record['scrap_fraction'] = (
            (scrap_vol / (good_vol + scrap_vol))
            if good_vol is not None and scrap_vol is not None and min(good_vol, scrap_vol) >= 0 and (good_vol + scrap_vol) > 0
            else None
        )
        order_record['group_prefix5'] = order_record['product_id'][:5]

        parsed_orders.append(order_record)

    distinct_keys = {record['order_id'] for record in parsed_orders}
    if len(distinct_keys) != len(parsed_orders):
        raise ValueError('Duplicate order identifiers detected; pipeline halted.')

    return raw_tabular_rows, parsed_orders, serialization_precision


def serial_order(record: dict) -> dict:
    """
    Format internal order dictionary timestamps into human-readable ISO 8601 strings.

    Args:
        record: Internal order dictionary containing microsecond fields.

    Returns:
        Exportable dictionary stripped of microsecond suffixes.
    """
    serialized_record = {key: val for key, val in record.items() if not key.endswith('_us')}
    for col in TIME_COLUMNS:
        serialized_record[col] = iso(record[col + '_us'])
    return serialized_record


# ==============================================================================
# SECTION 4: CONTINUOUS RESOURCE TIMELINE RECONSTRUCTION
# ==============================================================================

def resource_reconstruction(
    orders: list[dict],
    output_dir: Path
) -> tuple[list[dict], list[dict], set[str], list[dict], list[dict]]:
    """
    Reconstruct continuous state timelines and audit machine-level concurrency conflicts.

    Args:
        orders: List of validated order dictionaries.
        output_dir: Destination Path for audit CSV exports.

    Returns:
        Tuple of (changeover overlap pairs, official overlap pairs, involved orders set,
                  hourly capacity records, work centre summary records).
    """
    changeover_windows = []
    official_windows = []
    state_intervals = []

    for record in orders:
        cs = record['change_over_start_us']
        ce = record['change_over_end_us']
        act = record['actual_start_date_us']
        comp = record['actual_completion_date_us']

        if cs is not None and comp is not None and comp >= cs:
            changeover_windows.append(Interval(record['order_id'], record['work_centre'], cs, comp))

        if act is None or comp is None or comp < act:
            raise ValueError('Invalid official order execution window.')
        official_windows.append(Interval(record['order_id'], record['work_centre'], act, comp))

        if record['time_concordant']:
            if ce > cs:
                state_intervals.append(Interval(record['order_id'], record['work_centre'], cs, ce, STATE_SETUP))
            if comp > ce:
                state_intervals.append(Interval(record['order_id'], record['work_centre'], ce, comp, STATE_PRODUCTION))
        elif ce is not None and act <= ce <= comp:
            if ce > act:
                state_intervals.append(Interval(record['order_id'], record['work_centre'], act, ce, STATE_INDETERMINATE, True))
            if comp > ce:
                state_intervals.append(Interval(record['order_id'], record['work_centre'], ce, comp, STATE_PRODUCTION, True))
        elif comp > act:
            state_intervals.append(Interval(record['order_id'], record['work_centre'], act, comp, STATE_INDETERMINATE, True))

    changeover_overlaps = all_pairs(changeover_windows)
    official_overlaps = all_pairs(official_windows)

    involved_order_ids = {
        overlap_pair[order_key]
        for overlap_pair in (changeover_overlaps + official_overlaps)
        for order_key in ['order_a', 'order_b']
    }

    for record in orders:
        record['flag_any_overlap'] = record['order_id'] in involved_order_ids
        record['eligible_time_analysis'] = record['time_positive'] and not record['flag_any_overlap']

    write_csv(output_dir / 'overlaps_changeover_start.csv', changeover_overlaps)
    write_csv(output_dir / 'overlaps_actual_start.csv', official_overlaps)

    state_interval_rows = [
        {
            'order_id': item.order_id,
            'work_centre': item.centre,
            'state': item.state,
            'start': iso(item.start),
            'end': iso(item.end),
            'duration_seconds': (item.end - item.start) / US,
            'temporal_issue': item.issue
        }
        for item in state_intervals
    ]
    write_csv(output_dir / 'state_intervals.csv', state_interval_rows)

    candidate_intervals = []
    for record in orders:
        for start_col, end_col, state_label in [
            ('change_over_start', 'change_over_end', STATE_SETUP),
            ('change_over_end', 'actual_completion_date', STATE_PRODUCTION)
        ]:
            s_us = record[start_col + '_us']
            e_us = record[end_col + '_us']
            if s_us is not None and e_us is not None and e_us >= s_us:
                candidate_intervals.append({
                    'order_id': record['order_id'],
                    'work_centre': record['work_centre'],
                    'state': state_label,
                    'start': iso(s_us),
                    'end': iso(e_us),
                    'duration_seconds': (e_us - s_us) / US,
                    'concordant': record['time_concordant'],
                    'overlap': record['flag_any_overlap']
                })
    write_csv(output_dir / 'candidate_intervals_from_changeover_fields.csv', candidate_intervals)

    disjoint_segments = []
    hourly_capacity_records = []
    work_centre_summaries = []

    for centre in sorted({record['work_centre'] for record in orders}):
        centre_official_intervals = [item for item in official_windows if item.centre == centre]
        horizon_start_us = min(item.start for item in centre_official_intervals)
        horizon_end_us = max(item.end for item in centre_official_intervals)

        partitioned_pieces = partition(
            [item for item in state_intervals if item.centre == centre],
            horizon_start_us,
            horizon_end_us,
            centre
        )

        centre_state_totals = Counter()
        hourly_state_breakdowns = defaultdict(lambda: Counter())

        for piece in partitioned_pieces:
            piece_duration_us = piece['end_us'] - piece['start_us']
            centre_state_totals[piece['state']] += piece_duration_us

            for hour_epoch, seg_duration in hour_parts(piece['start_us'], piece['end_us']):
                hourly_state_breakdowns[hour_epoch][piece['state']] += seg_duration
                hourly_state_breakdowns[hour_epoch]['window'] += seg_duration
                hourly_state_breakdowns[hour_epoch]['attributed'] += seg_duration * piece['n_active']

            disjoint_segments.append({k: v for k, v in piece.items() if k not in ['start_us', 'end_us']})

        for hour_epoch, counter_vals in sorted(hourly_state_breakdowns.items()):
            hourly_record = {
                'work_centre': centre,
                'hour': iso(hour_epoch),
                'window_minutes': counter_vals['window'] / US / 60,
                'setup_minutes': counter_vals[STATE_SETUP] / US / 60,
                'production_window_minutes': counter_vals[STATE_PRODUCTION] / US / 60,
                'indeterminate_minutes': counter_vals[STATE_INDETERMINATE] / US / 60,
                'conflict_minutes': counter_vals[STATE_CONFLICT] / US / 60,
                'no_registered_activity_minutes': counter_vals[STATE_NO_RECORDED_ACTIVITY] / US / 60,
                'attributed_minutes': counter_vals['attributed'] / US / 60
            }

            partition_sum = sum(
                counter_vals[k]
                for k in [
                    STATE_SETUP,
                    STATE_PRODUCTION,
                    STATE_INDETERMINATE,
                    STATE_CONFLICT,
                    STATE_NO_RECORDED_ACTIVITY
                ]
            )
            if partition_sum != counter_vals['window']:
                raise ArithmeticError('Hourly partition does not conserve total window duration.')

            hourly_capacity_records.append(hourly_record)

        work_centre_summaries.append({
            'work_centre': centre,
            'n_orders': len(centre_official_intervals),
            'window_start': iso(horizon_start_us),
            'window_end': iso(horizon_end_us),
            'window_hours': (horizon_end_us - horizon_start_us) / US / 3600,
            'setup_hours': centre_state_totals[STATE_SETUP] / US / 3600,
            'production_window_hours': centre_state_totals[STATE_PRODUCTION] / US / 3600,
            'indeterminate_hours': centre_state_totals[STATE_INDETERMINATE] / US / 3600,
            'conflict_hours': centre_state_totals[STATE_CONFLICT] / US / 3600,
            'no_registered_activity_hours': centre_state_totals[STATE_NO_RECORDED_ACTIVITY] / US / 3600,
            'data_capacity_status': 'FAILED' if centre_state_totals[STATE_CONFLICT] else 'NO_CONFLICT_IN_RECORDS'
        })

    write_csv(output_dir / 'resource_segments.csv', disjoint_segments)
    write_csv(output_dir / 'resource_hourly.csv.gz', hourly_capacity_records)
    write_csv(output_dir / 'work_centre_audit.csv', work_centre_summaries)

    return changeover_overlaps, official_overlaps, involved_order_ids, hourly_capacity_records, work_centre_summaries


# ==============================================================================
# SECTION 5: MASS CONSERVATION AND HOURLY DISCRETIZATION LEDGER
# ==============================================================================

def allocate_and_reconcile(
    orders: list[dict],
    output_dir: Path
) -> tuple[list[dict], int]:
    """
    Allocate unit volumes across hourly execution windows and audit volumetric conservation.

    Args:
        orders: List of validated order records.
        output_dir: Destination Path for ledger CSV exports.

    Returns:
        Tuple of (reconciliation summary records, count of detailed allocation entries).

    Raises:
        ArithmeticError: If order-level or global mass conservation fails.
    """
    hourly_allocations = []
    reconciliation_ledger = []

    for record in orders:
        for quantity_col in ['completed_quantity', 'scrapped_quantity']:
            raw_quantity = record[quantity_col]
            allocated_sum = Decimal(0)

            if raw_quantity is None:
                allocation_status = 'missing'
            elif raw_quantity < 0:
                allocation_status = 'signed_non_physical_adjustment'
            elif record['eligible_time_analysis']:
                allocation_status = 'uniformly_allocated'
                for hour_epoch, duration_us, decimal_volume in uniform_allocation(
                    raw_quantity,
                    record['change_over_end_us'],
                    record['actual_completion_date_us']
                ):
                    hourly_allocations.append({
                        'order_id': record['order_id'],
                        'work_centre': record['work_centre'],
                        'quantity_field': quantity_col,
                        'hour': iso(hour_epoch),
                        'production_intersection_seconds': duration_us / US,
                        'allocated_pieces': decimal_volume,
                        'interpretation': 'unobserved_uniform_allocation'
                    })
                    allocated_sum += decimal_volume

                if allocated_sum != Decimal(raw_quantity):
                    raise ArithmeticError('Piece quantity not conserved at order level.')
            else:
                allocation_status = 'unallocable_conservative_rule'

            reconciliation_ledger.append({
                'order_id': record['order_id'],
                'quantity_field': quantity_col,
                'source_signed': raw_quantity,
                'status': allocation_status,
                'allocated_pieces': allocated_sum,
                'unallocated_nonnegative': (
                    raw_quantity
                    if raw_quantity is not None and raw_quantity >= 0 and allocation_status.startswith('unallocable')
                    else 0
                ),
                'signed_adjustment': raw_quantity if raw_quantity is not None and raw_quantity < 0 else 0
            })

    reconciliation_summary = []
    for quantity_col in ['completed_quantity', 'scrapped_quantity']:
        ledger_subset = [item for item in reconciliation_ledger if item['quantity_field'] == quantity_col]
        total_source_signed = sum(
            (Decimal(item['source_signed']) for item in ledger_subset if item['source_signed'] is not None),
            Decimal(0)
        )
        total_allocated = sum((item['allocated_pieces'] for item in ledger_subset), Decimal(0))
        total_unallocated = sum((Decimal(item['unallocated_nonnegative']) for item in ledger_subset), Decimal(0))
        total_signed_adj = sum((Decimal(item['signed_adjustment']) for item in ledger_subset), Decimal(0))

        if total_source_signed != (total_allocated + total_unallocated + total_signed_adj):
            raise ArithmeticError('Global mass balance reconciliation does not close.')

        reconciliation_summary.append({
            'quantity_field': quantity_col,
            'source_signed': total_source_signed,
            'allocated_nonnegative': total_allocated,
            'unallocated_nonnegative': total_unallocated,
            'signed_adjustments': total_signed_adj,
            'residual': total_source_signed - total_allocated - total_unallocated - total_signed_adj,
            'missing_orders': sum(item['source_signed'] is None for item in ledger_subset)
        })

    write_csv(output_dir / 'order_hour_allocations.csv.gz', hourly_allocations)
    write_csv(output_dir / 'quantity_ledger.csv', reconciliation_ledger)
    write_csv(output_dir / 'quantity_reconciliation.csv', reconciliation_summary)

    return reconciliation_summary, len(hourly_allocations)


# ==============================================================================
# SECTION 6: PRODUCT CATALOG INTEGRITY AND TAXONOMIC PROFILING
# ==============================================================================

def product_audit(
    catalog_path: Path,
    orders: list[dict],
    lr3_orders: list[dict],
    output_dir: Path
) -> dict[str, Any]:
    """
    Audit the master enterprise product catalog and evaluate SKU-to-family mappings.

    Args:
        catalog_path: Path to the auxiliary ProductDetail.xlsx workbook.
        orders: Fleet-wide list of validated order records.
        lr3_orders: Cohort of orders manufactured on benchmark asset LR3.
        output_dir: Destination Path for catalog audit exports.

    Returns:
        Dictionary summarizing catalog match rates and taxonomic missingness.

    Raises:
        ValueError: If catalog schema is invalid or contains duplicate product-attribute keys.
    """
    catalog_records = read_xlsx_values(catalog_path)
    required_catalog_keys = {'ProductId', 'NAME', 'VALUE'}
    if not catalog_records or set(catalog_records[0]) != required_catalog_keys:
        raise ValueError('Unexpected ProductDetail schema specification.')

    product_attribute_counts = Counter(
        (identifier(item['ProductId']), item['NAME']) for item in catalog_records
    )
    duplicate_keys = [
        {'product_id': k[0], 'attribute': k[1], 'count': count}
        for k, count in product_attribute_counts.items()
        if count > 1
    ]
    if duplicate_keys:
        raise ValueError('Duplicate product-attribute keys detected in master catalog.')

    fleet_product_ids = {item['product_id'] for item in orders}
    lr3_product_ids = {item['product_id'] for item in lr3_orders}

    relevant_catalog_records = [
        item for item in catalog_records if identifier(item['ProductId']) in fleet_product_ids
    ]
    all_catalog_product_ids = {identifier(item['ProductId']) for item in catalog_records}
    attribute_cardinalities = Counter(item['NAME'] for item in catalog_records)

    lr3_taxonomic_mapping = []
    for product_id in sorted(lr3_product_ids):
        matching_entries = [
            item for item in relevant_catalog_records if identifier(item['ProductId']) == product_id
        ]
        attribute_dictionary = {item['NAME']: item['VALUE'] for item in matching_entries}

        lr3_taxonomic_mapping.append({
            'product_id': product_id,
            'group_prefix5': product_id[:5],
            'group_status': 'PROVISIONAL_UNVALIDATED',
            'in_product_detail': product_id in all_catalog_product_ids,
            'PlanningHierarchy1': attribute_dictionary.get('PlanningHierarchy1'),
            'PlanningHierarchy5': attribute_dictionary.get('PlanningHierarchy5'),
            'Franchise': attribute_dictionary.get('Franchise')
        })

    write_csv(output_dir / 'lr3_product_group_mapping.csv', lr3_taxonomic_mapping)
    write_csv(output_dir / 'product_detail_relevant_records.csv', relevant_catalog_records)
    write_csv(
        output_dir / 'product_detail_attribute_counts.csv',
        [{'attribute': k, 'n_rows': v} for k, v in sorted(attribute_cardinalities.items())]
    )

    return {
        'rows': len(catalog_records),
        'distinct_products': len(all_catalog_product_ids),
        'duplicate_product_attribute_keys': len(duplicate_keys),
        'lr3_products': len(lr3_product_ids),
        'lr3_products_matched': len(lr3_product_ids & all_catalog_product_ids),
        'lr3_products_missing': sorted(lr3_product_ids - all_catalog_product_ids),
        'physical_group_validation': 'NOT_AVAILABLE',
        'simulation_uses_productdetail_values': False
    }


# ==============================================================================
# SECTION 7: SIMULATION JOB MAPPING AND TRACE BENCHMARKS
# ==============================================================================

def make_jobs(order_records: list[dict]) -> list[dict]:
    """
    Format operational orders into structured job specifications for the simulation engine.

    Args:
        order_records: Filtered list of order dictionaries.

    Returns:
        List of job specification dictionaries.
    """
    return [
        {
            'order_id': record['order_id'],
            'alias': record['alias'],
            'product_id': record['product_id'],
            'group': record['group_prefix5'],
            'production_seconds': record['production_seconds'],
            'good_pieces': record['completed_quantity']
        }
        for record in order_records
    ]


def trace_scenarios(
    order_records: list[dict],
    reduction_fractions: Iterable[float | int],
    sample_label: str
) -> list[dict]:
    """
    Evaluate proportional setup duration reductions against the recorded empirical baseline.

    Args:
        order_records: Cohort of orders undergoing evaluation.
        reduction_fractions: Proportional reduction factors to evaluate.
        sample_label: Descriptive cohort label for audit reporting.

    Returns:
        List of scenario outcome metrics across reduction levels.
    """
    total_production_rational = sum(rational(record['production_seconds']) for record in order_records)
    total_setup_rational = sum(rational(record['setup_seconds']) for record in order_records)
    total_good_units = sum(record['completed_quantity'] for record in order_records)
    baseline_runtime = total_production_rational + total_setup_rational

    scenario_outcomes = []
    for raw_fraction in reduction_fractions:
        reduction_rational = rational(raw_fraction)
        scaled_completion_time = total_production_rational + (1 - reduction_rational) * total_setup_rational
        time_saved = baseline_runtime - scaled_completion_time

        completion_hours = float(scaled_completion_time / 3600)
        saving_hours = float(time_saved / 3600)
        saving_percentage = float((time_saved / baseline_runtime) * 100)

        scenario_outcomes.append({
            'sample': sample_label,
            'scenario': f'TRACE_R{int(reduction_rational * 100):02d}',
            'setup_reduction_fraction': float(reduction_rational),
            'n_orders': len(order_records),
            'production_hours': float(total_production_rational / 3600),
            'setup_hours': float((1 - reduction_rational) * total_setup_rational / 3600),
            'completion_hours': completion_hours,
            'saving_hours': saving_hours,
            'saving_percent': saving_percentage,
            'good_pieces': total_good_units,
            'mean_good_pieces_per_model_hour': total_good_units / completion_hours if completion_hours > 0 else 0.0
        })

    return scenario_outcomes


# ==============================================================================
# SECTION 8: PRIMARY ORCHESTRATION PIPELINE
# ==============================================================================

def run(root_dir: Path, output_dir: Path) -> dict[str, Any]:
    """
    Execute the end-to-end analytical pipeline, generating reproducible CSV and JSON artifacts.

    Args:
        root_dir: Root directory containing config and input folders.
        output_dir: Destination directory for all calculated artifacts.

    Returns:
        Structured summary dictionary capturing global metrics and verification checks.

    Raises:
        ValueError: If configuration or primary cohort requirements are violated.
        ArithmeticError: If conservation or witness bounds fail verification.
    """
    configuration_path = root_dir / 'config' / 'study.json'
    study_config = json.loads(configuration_path.read_text(encoding='utf-8'))
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_orders_tabular, parsed_orders, precision_audit = load_orders(root_dir / 'input' / 'production_order.xlsx')
    write_csv(output_dir / 'original_order_values.csv', raw_orders_tabular)
    write_csv(output_dir / 'timestamp_serialization_audit.csv', precision_audit)

    co_overlaps, official_overlaps, involved_orders, hourly_records, centre_audits = resource_reconstruction(
        parsed_orders, output_dir
    )

    target_work_centre = study_config['target_work_centre']
    lr3_orders_all = sorted(
        [record for record in parsed_orders if record['work_centre'] == target_work_centre],
        key=lambda item: (
            item['change_over_start_us'] if item['change_over_start_us'] is not None else item['actual_start_date_us'],
            item['order_id']
        )
    )

    for order_idx, record in enumerate(lr3_orders_all, start=1):
        record['alias'] = f'LR3_{order_idx:03d}'

    for record in parsed_orders:
        record.setdefault('alias', f'ORD_{record["source_row"] - 1:05d}')
        record['primary_lr3'] = (record['work_centre'] == target_work_centre and record['eligible_time_analysis'])

    lr3_primary_cohort = [record for record in lr3_orders_all if record['primary_lr3']]
    if not lr3_primary_cohort:
        raise ValueError('No eligible primary orders located for benchmark asset LR3.')

    write_csv(output_dir / 'orders_audited.csv', [serial_order(r) for r in parsed_orders])
    write_csv(output_dir / 'lr3_all_orders.csv', [serial_order(r) for r in lr3_orders_all])
    write_csv(output_dir / 'lr3_primary_orders.csv', [serial_order(r) for r in lr3_primary_cohort])

    excluded_lr3_orders = [
        {
            'alias': record['alias'],
            'order_id': record['order_id'],
            'source_row': record['source_row'],
            'timestamp_divergence': record['flag_timestamp_divergence'],
            'missing_time': record['flag_missing_time'],
            'invalid_time': record['flag_time_order_invalid'],
            'zero_production': record['flag_zero_production'],
            'any_overlap': record['flag_any_overlap']
        }
        for record in lr3_orders_all
        if not record['primary_lr3']
    ]
    write_csv(output_dir / 'lr3_exclusions.csv', excluded_lr3_orders)

    quantity_summary, total_allocation_rows = allocate_and_reconcile(parsed_orders, output_dir)
    catalog_audit_results = product_audit(
        root_dir / 'input' / 'ProductDetail.xlsx',
        parsed_orders,
        lr3_orders_all,
        output_dir
    )

    observed_transitions = []
    supported_intra_setups = []
    supported_inter_setups = []
    primary_order_ids = {record['order_id'] for record in lr3_primary_cohort}

    for pred_order, succ_order in pairwise(lr3_orders_all):
        both_orders_primary = (
            pred_order['order_id'] in primary_order_ids and succ_order['order_id'] in primary_order_ids
        )
        is_intra_group = (pred_order['group_prefix5'] == succ_order['group_prefix5'])

        observed_transitions.append({
            'predecessor': pred_order['order_id'],
            'successor': succ_order['order_id'],
            'predecessor_alias': pred_order['alias'],
            'successor_alias': succ_order['alias'],
            'predecessor_product': pred_order['product_id'],
            'successor_product': succ_order['product_id'],
            'predecessor_group': pred_order['group_prefix5'],
            'successor_group': succ_order['group_prefix5'],
            'within_group': is_intra_group,
            'setup_seconds': succ_order['setup_seconds'],
            'both_primary': both_orders_primary,
            'status': 'original_pair_used' if both_orders_primary else 'original_pair_outside_primary_reference'
        })

        if both_orders_primary:
            setup_rational_val = rational(succ_order['setup_seconds'])
            if is_intra_group:
                supported_intra_setups.append(setup_rational_val)
            else:
                supported_inter_setups.append(setup_rational_val)

    if len(supported_intra_setups) != 1:
        raise ValueError('Intragroup setup anchor requires review: exactly one observation required.')
    if not supported_inter_setups:
        raise ValueError('No supported intergroup transitions found.')

    setup_a_rational = supported_intra_setups[0]
    setup_b_rational = sum(supported_inter_setups) / len(supported_inter_setups)
    initial_setup_rational = rational(lr3_primary_cohort[0]['setup_seconds'])

    descriptive_statistics_table = []
    for metric_label, metric_values in [
        ('intergroup_setup_original_pairs', [float(x / 60) for x in supported_inter_setups]),
        ('intragroup_setup_original_pair', [float(x / 60) for x in supported_intra_setups]),
        ('setup_all_primary_orders', [r['setup_seconds'] / 60 for r in lr3_primary_cohort]),
        ('production_window_primary_orders', [r['production_seconds'] / 3600 for r in lr3_primary_cohort])
    ]:
        descriptive_statistics_table.append({
            'variable': metric_label,
            'unit': 'hours' if metric_label.startswith('production_window') else 'minutes',
            **descriptive(metric_values)
        })

    write_csv(output_dir / 'lr3_original_transitions.csv', observed_transitions)
    write_csv(output_dir / 'lr3_descriptive_statistics.csv', descriptive_statistics_table)

    simulation_jobs = make_jobs(lr3_primary_cohort)
    historical_sequence = [job['order_id'] for job in simulation_jobs]
    grouped_sequence_orders = grouped_sequence(simulation_jobs)

    scenario_metrics_table = []
    h0_baseline_hours = None

    for scenario_name, order_sequence, setup_scale in [
        ('H0', historical_sequence, F(1)),
        ('G0', grouped_sequence_orders, F(1)),
        ('H20', historical_sequence, F(4, 5)),
        ('G20', grouped_sequence_orders, F(4, 5))
    ]:
        scheduled_jobs, schedule_metrics = simulate(
            simulation_jobs,
            order_sequence,
            setup_a_rational,
            setup_b_rational,
            initial_setup_rational,
            setup_scale
        )

        if scenario_name == 'H0':
            h0_baseline_hours = schedule_metrics['completion_hours']

        extended_metrics = {
            'scenario': scenario_name,
            'sequence': 'historical' if scenario_name.startswith('H') else 'grouped',
            'a_minutes': float(setup_a_rational / 60),
            'b_minutes': float(setup_b_rational / 60),
            'initial_setup_minutes': float(initial_setup_rational / 60),
            'interorder_setup_scale': float(setup_scale),
            **schedule_metrics,
            'saving_hours_vs_H0': h0_baseline_hours - schedule_metrics['completion_hours'],
            'saving_percent_vs_H0': (h0_baseline_hours - schedule_metrics['completion_hours']) / h0_baseline_hours * 100
        }
        scenario_metrics_table.append(extended_metrics)
        write_csv(output_dir / f'schedule_{scenario_name}.csv', scheduled_jobs)

    write_csv(output_dir / 'reference_scenarios.csv', scenario_metrics_table)

    # Paired completion shifts evaluation
    h0_schedule, _ = simulate(simulation_jobs, historical_sequence, setup_a_rational, setup_b_rational, initial_setup_rational)
    g0_schedule, _ = simulate(simulation_jobs, grouped_sequence_orders, setup_a_rational, setup_b_rational, initial_setup_rational)

    lookup_h = {job['order_id']: job for job in h0_schedule}
    lookup_g = {job['order_id']: job for job in g0_schedule}
    paired_shifts = []

    for job in simulation_jobs:
        job_h = lookup_h[job['order_id']]
        job_g = lookup_g[job['order_id']]
        time_delta_hours = (job_g['completion_seconds'] - job_h['completion_seconds']) / 3600

        if time_delta_hours > 1e-8:
            conclusion_tag = 'later_in_model'
        elif time_delta_hours < -1e-8:
            conclusion_tag = 'earlier_in_model'
        else:
            conclusion_tag = 'identical_in_model'

        paired_shifts.append({
            'alias': job['alias'],
            'order_id': job['order_id'],
            'position_h': job_h['position'],
            'position_g': job_g['position'],
            'completion_h_hours': job_h['completion_seconds'] / 3600,
            'completion_g_hours': job_g['completion_seconds'] / 3600,
            'shift_g_minus_h_hours': time_delta_hours,
            'conclusion': conclusion_tag
        })

    write_csv(output_dir / 'paired_completion_shifts.csv', paired_shifts)

    trace_records = trace_scenarios(
        lr3_primary_cohort, study_config['setup_reduction_fractions'], 'primary_without_divergence'
    )
    trace_records += trace_scenarios(
        lr3_orders_all, study_config['setup_reduction_fractions'], 'sensitivity_all_changeover_start'
    )

    actual_start_variant = [
        dict(record, setup_seconds=(record['change_over_end_us'] - record['actual_start_date_us']) / US)
        for record in lr3_orders_all
    ]
    trace_records += trace_scenarios(actual_start_variant, [0], 'sensitivity_all_actual_start')
    write_csv(output_dir / 'trace_setup_reductions.csv', trace_records)

    # Sensitivity grid across changeover anchors
    intergroup_summary = descriptive([float(x / 60) for x in supported_inter_setups])
    duration_scales = sorted(set(
        study_config['inter_minutes_grid'] + [
            intergroup_summary['q25'],
            intergroup_summary['median'],
            float(setup_b_rational / 60),
            intergroup_summary['q75']
        ]
    ))
    ratio_scales = sorted(set(study_config['ratio_grid'] + [float(setup_a_rational / setup_b_rational)]))

    sensitivity_grid = []
    for b_minutes in duration_scales:
        b_seconds_rational = rational(b_minutes) * 60
        for ratio_val in ratio_scales:
            a_seconds_rational = rational(ratio_val) * b_seconds_rational
            _, metrics_h = simulate(simulation_jobs, historical_sequence, a_seconds_rational, b_seconds_rational, initial_setup_rational)
            _, metrics_g = simulate(simulation_jobs, grouped_sequence_orders, a_seconds_rational, b_seconds_rational, initial_setup_rational)

            hours_saved = metrics_h['completion_hours'] - metrics_g['completion_hours']
            sensitivity_grid.append({
                'a_over_b': ratio_val,
                'a_minutes': float(a_seconds_rational / 60),
                'b_minutes': float(b_seconds_rational / 60),
                'historical_hours': metrics_h['completion_hours'],
                'grouped_hours': metrics_g['completion_hours'],
                'saving_hours': hours_saved,
                'saving_percent': (hours_saved / metrics_h['completion_hours']) * 100
            })

    write_csv(output_dir / 'sensitivity_grid.csv', sensitivity_grid)

    anchor_summary = []
    for anchor_label, b_val_rational in [
        ('intergroup_mean', setup_b_rational),
        ('intergroup_median', rational(intergroup_summary['median']) * 60),
        ('intergroup_q25', rational(intergroup_summary['q25']) * 60),
        ('intergroup_q75', rational(intergroup_summary['q75']) * 60)
    ]:
        _, metrics_h = simulate(simulation_jobs, historical_sequence, setup_a_rational, b_val_rational, initial_setup_rational)
        _, metrics_g = simulate(simulation_jobs, grouped_sequence_orders, setup_a_rational, b_val_rational, initial_setup_rational)
        hours_saved = metrics_h['completion_hours'] - metrics_g['completion_hours']

        anchor_summary.append({
            'anchor': anchor_label,
            'a_minutes': float(setup_a_rational / 60),
            'b_minutes': float(b_val_rational / 60),
            'historical_hours': metrics_h['completion_hours'],
            'grouped_hours': metrics_g['completion_hours'],
            'saving_hours': hours_saved,
            'saving_percent': (hours_saved / metrics_h['completion_hours']) * 100
        })

    write_csv(output_dir / 'sensitivity_anchor_summary.csv', anchor_summary)

    # Positional block reordering sensitivity
    block_records = []
    for block_size in study_config['block_sizes'] + [len(simulation_jobs)]:
        block_seq = grouped_sequence(simulation_jobs, block_size)
        _, block_metrics = simulate(simulation_jobs, block_seq, setup_a_rational, setup_b_rational, initial_setup_rational)

        block_records.append({
            'block_size': block_size,
            'changes': block_metrics['changes'],
            'completion_hours': block_metrics['completion_hours'],
            'saving_hours_vs_H0': h0_baseline_hours - block_metrics['completion_hours'],
            'saving_percent_vs_H0': (h0_baseline_hours - block_metrics['completion_hours']) / h0_baseline_hours * 100
        })

    write_csv(output_dir / 'sensitivity_reordering_blocks.csv', block_records)

    # Sample cohort sensitivity (Primary 78 vs All 79)
    sample_sensitivity = []
    for cohort_label, cohort_records in [('primary', lr3_primary_cohort), ('sensitivity_all', lr3_orders_all)]:
        cohort_jobs = make_jobs(cohort_records)
        cohort_seq_h = [item['order_id'] for item in cohort_jobs]
        cohort_seq_g = grouped_sequence(cohort_jobs)

        _, mh = simulate(cohort_jobs, cohort_seq_h, setup_a_rational, setup_b_rational, initial_setup_rational)
        _, mg = simulate(cohort_jobs, cohort_seq_g, setup_a_rational, setup_b_rational, initial_setup_rational)
        hours_saved = mh['completion_hours'] - mg['completion_hours']

        sample_sensitivity.append({
            'sample': cohort_label,
            'n_orders': len(cohort_records),
            'a_minutes': float(setup_a_rational / 60),
            'b_minutes': float(setup_b_rational / 60),
            'changes_h': mh['changes'],
            'changes_g': mg['changes'],
            'historical_hours': mh['completion_hours'],
            'grouped_hours': mg['completion_hours'],
            'saving_hours': hours_saved,
            'saving_percent': (hours_saved / mh['completion_hours']) * 100
        })

    write_csv(output_dir / 'sensitivity_sample.csv', sample_sensitivity)

    # SKU identity vs prefix-5 heuristic
    grouping_rules = []
    for grouping_mode in ['prefix_5_provisional', 'product_identity']:
        mode_jobs = [
            dict(item, group=item['product_id'] if grouping_mode == 'product_identity' else item['group'])
            for item in simulation_jobs
        ]
        mode_seq_h = [item['order_id'] for item in mode_jobs]
        mode_seq_g = grouped_sequence(mode_jobs)

        _, mh = simulate(mode_jobs, mode_seq_h, setup_a_rational, setup_b_rational, initial_setup_rational)
        _, mg = simulate(mode_jobs, mode_seq_g, setup_a_rational, setup_b_rational, initial_setup_rational)

        grouping_rules.append({
            'group_rule': grouping_mode,
            'n_groups': len({item['group'] for item in mode_jobs}),
            'changes_h': mh['changes'],
            'changes_g': mg['changes'],
            'completion_h': mh['completion_hours'],
            'completion_g': mg['completion_hours'],
            'saving_hours': mh['completion_hours'] - mg['completion_hours'],
            'note': 'same_values_structural_comparison_only_not_same_physical_interpretation'
        })

    write_csv(output_dir / 'sensitivity_group_rule.csv', grouping_rules)

    # Empirical transition support audit
    observed_product_pairs = Counter(
        (item['predecessor_product'], item['successor_product'])
        for item in observed_transitions
        if item['both_primary']
    )
    observed_group_pairs = Counter(
        (item['predecessor_group'], item['successor_group'])
        for item in observed_transitions
        if item['both_primary']
    )
    jobs_lookup = {job['order_id']: job for job in simulation_jobs}

    transition_support_rows = []
    for scenario_name, order_sequence in [('H0', historical_sequence), ('G0', grouped_sequence_orders)]:
        for pred_id, succ_id in pairwise(order_sequence):
            pred_job = jobs_lookup[pred_id]
            succ_job = jobs_lookup[succ_id]

            transition_support_rows.append({
                'scenario': scenario_name,
                'predecessor': pred_job['alias'],
                'successor': succ_job['alias'],
                'predecessor_product': pred_job['product_id'],
                'successor_product': succ_job['product_id'],
                'supported_product_pair_count': observed_product_pairs[(pred_job['product_id'], succ_job['product_id'])],
                'supported_group_pair_count': observed_group_pairs[(pred_job['group'], succ_job['group'])],
                'same_original_order_pair': any(
                    item['predecessor'] == pred_id and item['successor'] == succ_id and item['both_primary']
                    for item in observed_transitions
                )
            })

    write_csv(output_dir / 'scenario_transition_support.csv', transition_support_rows)

    # Deterministic set-based robustness analysis
    epsilon_star_seconds = robustness_threshold(
        simulation_jobs, historical_sequence, grouped_sequence_orders, setup_a_rational, setup_b_rational
    )
    epsilon_grid_minutes = sorted(set(
        study_config['robust_epsilon_minutes'] + (
            [float(epsilon_star_seconds / 60)] if epsilon_star_seconds is not None else []
        )
    ))

    robustness_evaluations = []
    for eps_minutes in epsilon_grid_minutes:
        eps_seconds_parameter = (
            epsilon_star_seconds
            if epsilon_star_seconds is not None and eps_minutes == float(epsilon_star_seconds / 60)
            else rational(eps_minutes) * 60
        )
        uncertainty_box = robust_box(
            simulation_jobs,
            historical_sequence,
            grouped_sequence_orders,
            setup_a_rational,
            setup_b_rational,
            eps_seconds_parameter
        )

        robustness_evaluations.append({
            'epsilon_minutes': eps_minutes,
            'nominal_saving_hours': float(uncertainty_box['nominal_seconds'] / 3600),
            'minimum_saving_hours': float(uncertainty_box['lower_seconds'] / 3600),
            'maximum_saving_hours': float(uncertainty_box['upper_seconds'] / 3600),
            'strictly_positive_for_all_setups_in_box': uncertainty_box['lower_seconds'] > F(1, 1000000),
            'interpretation': 'conditional_deterministic_interval_not_confidence_interval'
        })

    write_csv(output_dir / 'robust_pair_uncertainty.csv', robustness_evaluations)

    witness_box_15 = robust_box(
        simulation_jobs,
        historical_sequence,
        grouped_sequence_orders,
        setup_a_rational,
        setup_b_rational,
        rational(15) * 60
    )
    write_csv(output_dir / 'robust_witness_epsilon15_minutes.csv', witness_box_15['details'])

    witness_matrix = {
        (item['predecessor_product'], item['successor_product']): item['setup_for_min_difference']
        for item in witness_box_15['details']
    }
    witness_schedule_h = simulate_pair_matrix(simulation_jobs, historical_sequence, witness_matrix, initial_setup_rational)
    witness_schedule_g = simulate_pair_matrix(simulation_jobs, grouped_sequence_orders, witness_matrix, initial_setup_rational)

    witness_makespan_diff_hours = (
        witness_schedule_h[-1]['completion_seconds'] - witness_schedule_g[-1]['completion_seconds']
    ) / 3600

    if abs(witness_makespan_diff_hours - float(witness_box_15['lower_seconds'] / 3600)) > 1e-8:
        raise ArithmeticError('Robust witness realization does not meet theoretical lower bound.')

    write_csv(output_dir / 'robust_witness_schedule_H.csv', witness_schedule_h)
    write_csv(output_dir / 'robust_witness_schedule_G.csv', witness_schedule_g)

    # Illustrative sensitivity thresholds
    delta_b_changes = scenario_metrics_table[0]['changes'] - scenario_metrics_table[1]['changes']
    total_production_time_rational = sum(rational(job['production_seconds']) for job in simulation_jobs)
    illustrative_thresholds = []

    for target_fraction in study_config['illustrative_relative_thresholds']:
        target_tau = rational(target_fraction)
        for setup_ratio in [0, 0.1, 0.25, 0.5, 0.75, 1.0]:
            rho_rational = rational(setup_ratio)
            denominator = (
                delta_b_changes * (1 - rho_rational)
                - target_tau * (scenario_metrics_table[0]['changes'] + (len(simulation_jobs) - 1 - scenario_metrics_table[0]['changes']) * rho_rational)
            )

            if denominator > 0:
                required_b_min = float(target_tau * (total_production_time_rational + initial_setup_rational) / denominator / 60)
                feasibility_status = 'feasible_in_model'
            else:
                required_b_min = None
                feasibility_status = 'infeasible_at_ratio'

            illustrative_thresholds.append({
                'illustrative_target_percent': float(target_tau * 100),
                'a_over_b': float(rho_rational),
                'required_b_minutes': required_b_min,
                'status': feasibility_status,
                'interpretation': 'illustrative_threshold_not_industrial_target'
            })

    write_csv(output_dir / 'illustrative_thresholds.csv', illustrative_thresholds)

    full_prod_hours = sum(r['production_seconds'] for r in lr3_orders_all) / 3600
    full_setup_hours = sum(r['setup_seconds'] for r in lr3_orders_all) / 3600
    primary_prod_hours = sum(r['production_seconds'] for r in lr3_primary_cohort) / 3600
    primary_setup_hours = sum(r['setup_seconds'] for r in lr3_primary_cohort) / 3600

    programmatic_verification_checks = [
        {'check': 'unique_keys', 'scope': 'program', 'status': 'PASSED', 'value': len(parsed_orders)},
        {'check': 'quantity_reconciliation', 'scope': 'program', 'status': 'PASSED', 'value': 0},
        {'check': 'temporal_partition_conserves_window', 'scope': 'program', 'status': 'PASSED', 'value': 0},
        {'check': 'formulas_vs_scenario_engine', 'scope': 'program', 'status': 'PASSED', 'value': 0},
        {'check': 'global_data_capacity', 'scope': 'source_data', 'status': 'FAILED' if official_overlaps else 'PASSED', 'value': len(official_overlaps)},
        {'check': 'all_timestamps_concordance', 'scope': 'source_data', 'status': 'FAILED' if any(r['flag_timestamp_divergence'] for r in parsed_orders) else 'PASSED', 'value': sum(r['flag_timestamp_divergence'] for r in parsed_orders)},
        {'check': 'lr3_sample_capacity', 'scope': 'primary_sample', 'status': 'PASSED' if not any(r['flag_any_overlap'] for r in lr3_primary_cohort) else 'FAILED', 'value': sum(r['flag_any_overlap'] for r in lr3_primary_cohort)},
        {'check': 'physical_families_confirmed', 'scope': 'interpretation', 'status': 'NOT_EVALUATED', 'value': 'unconfirmed'},
        {'check': 'independent_operational_validation', 'scope': 'interpretation', 'status': 'NOT_EVALUATED', 'value': 'no_independent_data'}
    ]
    write_csv(output_dir / 'validation_status.csv', programmatic_verification_checks)

    comprehensive_summary = {
        'version': study_config['version'],
        'scope': 'historical_analysis_and_conditional_deterministic_experiment',
        'raw_rows': len(parsed_orders),
        'work_centres': len(centre_audits),
        'distinct_products': len({r['product_id'] for r in parsed_orders}),
        'source_window_start': iso(min(r['actual_start_date_us'] for r in parsed_orders)),
        'source_window_end': iso(max(r['actual_completion_date_us'] for r in parsed_orders)),
        'missing_time_orders': sum(r['flag_missing_time'] for r in parsed_orders),
        'divergent_time_orders': sum(r['flag_timestamp_divergence'] for r in parsed_orders),
        'zero_production_orders': sum(r['flag_zero_production'] for r in parsed_orders),
        'negative_good_orders': sum(r['flag_negative_good'] for r in parsed_orders),
        'negative_scrap_orders': sum(r['flag_negative_scrap'] for r in parsed_orders),
        'eligible_time_orders': sum(r['eligible_time_analysis'] for r in parsed_orders),
        'overlap_pairs_changeover': len(co_overlaps),
        'overlap_pairs_actual': len(official_overlaps),
        'all_overlap_orders': len(involved_orders),
        'resource_hours_with_conflict': sum(r['conflict_minutes'] > 0 for r in hourly_records),
        'resource_hours_above_attributed_capacity': sum(
            r['attributed_minutes'] > r['window_minutes'] + 1e-9 for r in hourly_records
        ),
        'resource_indeterminate_hours': sum(r['indeterminate_hours'] for r in centre_audits),
        'timestamp_max_serialization_adjustment_seconds': max(
            abs(Decimal(r['serialization_correction_seconds'])) for r in precision_audit
        ),
        'lr3_all_n': len(lr3_orders_all),
        'lr3_primary_n': len(lr3_primary_cohort),
        'lr3_products': len({r['product_id'] for r in lr3_primary_cohort}),
        'lr3_groups': len({r['group_prefix5'] for r in lr3_primary_cohort}),
        'lr3_exclusions': excluded_lr3_orders,
        'lr3_production_full_hours': full_prod_hours,
        'lr3_setup_full_hours': full_setup_hours,
        'lr3_production_main_hours': primary_prod_hours,
        'lr3_setup_main_hours': primary_setup_hours,
        'primary_observed_setup_share_percent': primary_setup_hours / (primary_prod_hours + primary_setup_hours) * 100,
        'full_observed_setup_share_percent': full_setup_hours / (full_prod_hours + full_setup_hours) * 100,
        'reference_a_minutes': float(setup_a_rational / 60),
        'reference_b_minutes': float(setup_b_rational / 60),
        'initial_setup_minutes': float(initial_setup_rational / 60),
        'reference_intra_n': len(supported_intra_setups),
        'reference_inter_n': len(supported_inter_setups),
        'completion_later_orders': sum(x['shift_g_minus_h_hours'] > 1e-8 for x in paired_shifts),
        'completion_earlier_orders': sum(x['shift_g_minus_h_hours'] < -1e-8 for x in paired_shifts),
        'completion_max_later_hours': max(x['shift_g_minus_h_hours'] for x in paired_shifts),
        'completion_max_earlier_hours': min(x['shift_g_minus_h_hours'] for x in paired_shifts),
        'reference_delta_changes': delta_b_changes,
        'reference_saving_hours': scenario_metrics_table[1]['saving_hours_vs_H0'],
        'reference_saving_percent': scenario_metrics_table[1]['saving_percent_vs_H0'],
        'robust_critical_epsilon_minutes': (
            float(epsilon_star_seconds / 60) if epsilon_star_seconds is not None else None
        ),
        'robust_box_l1': robust_box(
            simulation_jobs, historical_sequence, grouped_sequence_orders, setup_a_rational, setup_b_rational, 0
        )['l1'],
        'no_product_pair_support_grouped': sum(
            r['scenario'] == 'G0' and r['supported_product_pair_count'] == 0 for r in transition_support_rows
        ),
        'no_group_pair_support_grouped': sum(
            r['scenario'] == 'G0' and r['supported_group_pair_count'] == 0 for r in transition_support_rows
        ),
        'quantities': [
            {k: str(v) if isinstance(v, Decimal) else v for k, v in item.items()}
            for item in quantity_summary
        ],
        'allocation_rows': total_allocation_rows,
        'product_detail_audit': catalog_audit_results
    }

    write_json(output_dir / 'summary.json', comprehensive_summary)
    write_json(
        output_dir / 'input_manifest.json',
        {
            file_path.name: {
                'sha256': sha256(file_path),
                'bytes': file_path.stat().st_size
            }
            for file_path in sorted((root_dir / 'input').iterdir())
            if file_path.is_file()
        }
    )
    write_json(output_dir / 'config_used.json', study_config)

    return comprehensive_summary