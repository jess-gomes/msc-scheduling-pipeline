# ==============================================================================
# MODULE: CLOSED-LOT DETERMINISTIC SCHEDULING AND SETUP BENCHMARK (model.py)
# ==============================================================================
# Implements the closed-lot deterministic single-machine sequencing model,
# homogeneous two-parameter changeover cost functions, makespan evaluation,
# and exact set-based robustness analysis over parameter uncertainty boxes.
# ==============================================================================

from __future__ import annotations

from collections import Counter, defaultdict
from fractions import Fraction as F
from itertools import pairwise
import math
from typing import Any, Callable

# ==============================================================================
# SECTION 1: ARITHMETIC CONVERSION AND DOMAIN VALIDATION HELPERS
# ==============================================================================

def rational(value: Any) -> F:
    """
    Convert a numeric input into an exact rational Fraction representation.

    Args:
        value: Integer, string, float, or Fraction instance to convert.

    Returns:
        Exact Fraction representation of the input value.

    Raises:
        ValueError: If a float input is non-finite (infinite or NaN).
    """
    if isinstance(value, F):
        return value
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Non-finite numeric parameter cannot be converted to rational.')
    return F(str(value))


def validate_jobs(jobs: list[dict]) -> None:
    """
    Verify structural validity, distinctness, and positivity of simulation jobs.

    Args:
        jobs: List of job specification dictionaries.

    Raises:
        ValueError: If the job list is empty, contains duplicate order identifiers,
            exhibits non-positive productive duration, or lacks family group tokens.
    """
    if not jobs:
        raise ValueError('Empty job specification collection.')

    order_identifiers = [job['order_id'] for job in jobs]
    if len(set(order_identifiers)) != len(order_identifiers):
        raise ValueError('Duplicate order identifiers detected in job collection.')

    for job in jobs:
        if rational(job['production_seconds']) <= 0:
            raise ValueError('Non-positive productive duration detected in job record.')
        if not job.get('group'):
            raise ValueError('Missing tooling family group identifier in job record.')


# ==============================================================================
# SECTION 2: HEURISTIC GROUPING AND SEQUENCE PERMUTATION
# ==============================================================================

def grouped_sequence(jobs: list[dict], block_size: int | None = None) -> list[str]:
    """
    Generate a stable family-grouped dispatching sequence across operational blocks.

    Within each consecutive positional block of size block_size, orders sharing
    identical tooling families are clustered contiguously according to first occurrence.
    Internal order within each family cluster preserves historical arrival priority.
    The initial order of the schedule remains strictly anchored at position index zero.

    Args:
        jobs: Chronologically ordered list of job dictionaries.
        block_size: Number of consecutive positions per reordering partition.
            Defaults to the entire cohort length if None.

    Returns:
        List of order identifiers representing the permuted schedule sequence.

    Raises:
        ValueError: If block_size is specified as an integer strictly less than one.
    """
    validate_jobs(jobs)
    if block_size is not None and block_size < 1:
        raise ValueError('Reordering block size must be a strictly positive integer.')

    effective_block_size = block_size or len(jobs)
    permuted_sequence: list[str] = []

    for block_start_idx in range(0, len(jobs), effective_block_size):
        family_clusters: dict[str, list[str]] = {}
        for job in jobs[block_start_idx:block_start_idx + effective_block_size]:
            family_clusters.setdefault(job['group'], []).append(job['order_id'])

        for clustered_order_ids in family_clusters.values():
            permuted_sequence.extend(clustered_order_ids)

    return permuted_sequence


# ==============================================================================
# SECTION 3: DETERMINISTIC RECURRENCE AND MAKESPAN SIMULATION
# ==============================================================================

def simulate(
    jobs: list[dict],
    sequence: list[str],
    a: Any,
    b: Any,
    s0: Any,
    scale: Any = 1
) -> tuple[list[dict], dict[str, Any]]:
    """
    Simulate single-machine execution under the two-parameter changeover function s_ij(a, b).

    Evaluates completion timestamps along the schedule via forward recurrence,
    auditing numerical exactness against the closed-form combinatorial formula:
    C_max = sum(p_j) + s0 + scale * ((n - 1 - Delta_B) * a + Delta_B * b).

    Args:
        jobs: List of job specification dictionaries.
        sequence: Ordered list of job order_ids defining dispatch order.
        a: Intragroup setup duration parameter (homogeneous baseline).
        b: Intergroup setup duration parameter (major changeover).
        s0: Boundary setup duration for the initial order.
        scale: Proportional setup duration contraction multiplier. Defaults to 1.

    Returns:
        Tuple of (detailed order execution records, aggregated schedule metrics dictionary).

    Raises:
        ValueError: If sequence length or membership does not match jobs, initial order
            is altered, or setup parameters are strictly negative.
        ArithmeticError: If forward recurrence diverges from the analytical closed form.
    """
    validate_jobs(jobs)
    if len(sequence) != len(jobs) or set(sequence) != {job['order_id'] for job in jobs}:
        raise ValueError('Dispatch sequence must contain each candidate order exactly once.')

    if sequence[0] != jobs[0]['order_id']:
        raise ValueError('Initial condition violation: boundary order must remain fixed at position zero.')

    rational_a, rational_b, rational_s0, rational_scale = map(rational, (a, b, s0, scale))
    if min(rational_a, rational_b, rational_s0, rational_scale) < 0:
        raise ValueError('Negative setup duration or scale factor is physically unauthorized.')

    jobs_lookup = {job['order_id']: job for job in jobs}
    simulation_clock = F(0)
    cumulative_setup_duration = F(0)
    intergroup_changeover_count = 0
    detailed_execution_records = []

    for position_index, order_id in enumerate(sequence):
        current_job = jobs_lookup[order_id]
        is_intergroup_transition = (
            position_index > 0
            and jobs_lookup[sequence[position_index - 1]]['group'] != current_job['group']
        )

        if position_index == 0:
            applied_setup_seconds = rational_s0
        else:
            base_setup = rational_b if is_intergroup_transition else rational_a
            applied_setup_seconds = rational_scale * base_setup

        job_production_seconds = rational(current_job['production_seconds'])
        setup_start_epoch = simulation_clock
        production_start_epoch = setup_start_epoch + applied_setup_seconds
        simulation_clock = production_start_epoch + job_production_seconds

        cumulative_setup_duration += applied_setup_seconds
        intergroup_changeover_count += int(is_intergroup_transition)

        detailed_execution_records.append({
            'position': position_index + 1,
            'order_id': order_id,
            'alias': current_job['alias'],
            'product_id': current_job['product_id'],
            'group': current_job['group'],
            'predecessor': sequence[position_index - 1] if position_index > 0 else '',
            'setup_start_seconds': float(setup_start_epoch),
            'setup_seconds': float(applied_setup_seconds),
            'production_start_seconds': float(production_start_epoch),
            'production_seconds': float(job_production_seconds),
            'completion_seconds': float(simulation_clock),
            'good_pieces': current_job.get('good_pieces')
        })

    total_productive_seconds = sum((rational(job['production_seconds']) for job in jobs), F(0))
    intragroup_transition_count = len(jobs) - 1 - intergroup_changeover_count

    analytical_completion_seconds = (
        total_productive_seconds
        + rational_s0
        + rational_scale * (intragroup_transition_count * rational_a + intergroup_changeover_count * rational_b)
    )

    if simulation_clock != analytical_completion_seconds:
        raise ArithmeticError('Discrepancy detected between forward recurrence and analytical closed form.')

    all_good_pieces_present = all(job.get('good_pieces') is not None for job in jobs)
    total_conforming_units = (
        sum(job['good_pieces'] for job in jobs) if all_good_pieces_present else None
    )

    completion_time_hours = float(simulation_clock / 3600)
    throughput_conforming_per_hour = (
        total_conforming_units / completion_time_hours
        if total_conforming_units is not None and completion_time_hours > 0
        else None
    )

    summary_metrics = {
        'n_orders': len(jobs),
        'changes': intergroup_changeover_count,
        'within_transitions': intragroup_transition_count,
        'production_hours': float(total_productive_seconds / 3600),
        'setup_hours': float(cumulative_setup_duration / 3600),
        'completion_hours': completion_time_hours,
        'good_pieces': total_conforming_units,
        'mean_good_pieces_per_model_hour': throughput_conforming_per_hour
    }

    return detailed_execution_records, summary_metrics


# ==============================================================================
# SECTION 4: DIRECTED PRODUCT TRANSITION CARDINALITIES
# ==============================================================================

def pair_counts(jobs: list[dict], sequence: list[str]) -> Counter:
    """
    Extract directed product transition counts along a dispatch sequence.

    Args:
        jobs: List of job dictionaries providing SKU cross-referencing.
        sequence: Ordered sequence of order identifiers.

    Returns:
        Counter mapping directed product tuples (pred_product_id, succ_product_id) to frequencies.
    """
    jobs_lookup = {job['order_id']: job for job in jobs}
    return Counter(
        (jobs_lookup[pred_id]['product_id'], jobs_lookup[succ_id]['product_id'])
        for pred_id, succ_id in pairwise(sequence)
    )


# ==============================================================================
# SECTION 5: SET-BASED ROBUSTNESS ANALYSIS AND UNCERTAINTY BOXES
# ==============================================================================

def robust_box(
    jobs: list[dict],
    seq_h: list[str],
    seq_g: list[str],
    a: Any,
    b: Any,
    epsilon: Any
) -> dict[str, Any]:
    """
    Evaluate exact analytical bounds on makespan contraction over perturbation set U_epsilon.

    Assumes identical directed product transitions experience identical setup durations
    across both schedules. For each directed transition e = (i, j), setup duration satisfies
    s_e in [max(0, nominal_e - epsilon), nominal_e + epsilon].

    Args:
        jobs: List of job dictionaries.
        seq_h: Historical baseline sequence order identifiers.
        seq_g: Grouped candidate sequence order identifiers.
        a: Nominal intragroup setup duration parameter.
        b: Nominal intergroup setup duration parameter.
        epsilon: Radius of the perturbation box in seconds.

    Returns:
        Dictionary capturing lower, upper, and nominal savings in seconds, L1 norm, and details.

    Raises:
        ValueError: If nominal setup parameters or epsilon radius are negative.
    """
    rational_a, rational_b, rational_epsilon = map(rational, (a, b, epsilon))
    if min(rational_a, rational_b, rational_epsilon) < 0:
        raise ValueError('Negative setup baseline or uncertainty radius in robustness evaluation.')

    counts_historical = pair_counts(jobs, seq_h)
    counts_grouped = pair_counts(jobs, seq_g)
    sku_to_group = {job['product_id']: job['group'] for job in jobs}

    lower_saving_seconds = F(0)
    upper_saving_seconds = F(0)
    nominal_saving_seconds = F(0)
    l1_norm_accumulated = 0
    transition_edge_details = []

    all_directed_edges = sorted(set(counts_historical.keys()) | set(counts_grouped.keys()))

    for edge in all_directed_edges:
        coefficient = counts_historical[edge] - counts_grouped[edge]
        is_intra = (sku_to_group[edge[0]] == sku_to_group[edge[1]])
        nominal_setup = rational_a if is_intra else rational_b

        lower_setup_bound = max(F(0), nominal_setup - rational_epsilon)
        upper_setup_bound = nominal_setup + rational_epsilon

        # Select adversarial extrema based on coefficient sign
        if coefficient >= 0:
            setup_for_min = lower_setup_bound
            setup_for_max = upper_setup_bound
        else:
            setup_for_min = upper_setup_bound
            setup_for_max = lower_setup_bound

        lower_saving_seconds += coefficient * setup_for_min
        upper_saving_seconds += coefficient * setup_for_max
        nominal_saving_seconds += coefficient * nominal_setup
        l1_norm_accumulated += abs(coefficient)

        transition_edge_details.append({
            'predecessor_product': edge[0],
            'successor_product': edge[1],
            'count_h': counts_historical[edge],
            'count_g': counts_grouped[edge],
            'coefficient': coefficient,
            'nominal_seconds': float(nominal_setup),
            'lower_seconds': float(lower_setup_bound),
            'upper_seconds': float(upper_setup_bound),
            'setup_for_min_difference': float(setup_for_min),
            'setup_for_max_difference': float(setup_for_max)
        })

    return {
        'lower_seconds': lower_saving_seconds,
        'upper_seconds': upper_saving_seconds,
        'nominal_seconds': nominal_saving_seconds,
        'l1': l1_norm_accumulated,
        'details': transition_edge_details
    }


def robustness_threshold(
    jobs: list[dict],
    seq_h: list[str],
    seq_g: list[str],
    a: Any,
    b: Any
) -> F | None:
    """
    Identify the critical perturbation threshold epsilon_star where lower saving boundary reaches zero.

    Exploits piecewise linearity of the lower bound function across critical breakpoint intervals.

    Args:
        jobs: List of job dictionaries.
        seq_h: Historical baseline sequence order identifiers.
        seq_g: Grouped candidate sequence order identifiers.
        a: Nominal intragroup setup duration parameter.
        b: Nominal intergroup setup duration parameter.

    Returns:
        Exact rational threshold epsilon_star in seconds, or None if lower saving remains strictly positive.
    """
    rational_a, rational_b = map(rational, (a, b))
    breakpoint_candidates = sorted(set([F(0), rational_a, rational_b, max(rational_a, rational_b) + F(1)]))

    for interval_start, interval_end in pairwise(breakpoint_candidates):
        val_start = robust_box(jobs, seq_h, seq_g, rational_a, rational_b, interval_start)['lower_seconds']
        val_end = robust_box(jobs, seq_h, seq_g, rational_a, rational_b, interval_end)['lower_seconds']

        if val_start <= 0:
            return interval_start
        if val_end <= 0:
            # Linear interpolation between breakpoints
            return interval_start + val_start * (interval_end - interval_start) / (val_start - val_end)

    terminal_point = breakpoint_candidates[-1]
    val_terminal = robust_box(jobs, seq_h, seq_g, rational_a, rational_b, terminal_point)['lower_seconds']
    val_terminal_extended = robust_box(jobs, seq_h, seq_g, rational_a, rational_b, terminal_point + 1)['lower_seconds']

    if val_terminal <= 0:
        return terminal_point
    if val_terminal_extended < val_terminal:
        return terminal_point + val_terminal / (val_terminal - val_terminal_extended)

    return None


# ==============================================================================
# SECTION 6: ADVERSARIAL WITNESS MATRIX RECONSTRUCTION
# ==============================================================================

def simulate_pair_matrix(
    jobs: list[dict],
    sequence: list[str],
    setup_by_pair: dict[tuple[str, str], Any],
    s0: Any
) -> list[dict]:
    """
    Simulate execution under an explicit transition setup duration matrix.

    Used to materialize adversarial witness schedules matching theoretical lower bounds.

    Args:
        jobs: List of job specification dictionaries.
        sequence: Ordered sequence of order identifiers.
        setup_by_pair: Mapping of directed SKU pairs (pred_product_id, succ_product_id) to durations.
        s0: Boundary setup duration for the initial order.

    Returns:
        List of detailed order completion records under the specified matrix.

    Raises:
        ValueError: If sequence is invalid, initial order is altered, a transition
            is missing from the matrix, or a setup duration is negative.
    """
    validate_jobs(jobs)
    if len(sequence) != len(jobs) or set(sequence) != {job['order_id'] for job in jobs}:
        raise ValueError('Dispatch sequence must contain each candidate order exactly once.')

    if sequence[0] != jobs[0]['order_id']:
        raise ValueError('Initial condition violation: boundary order must remain fixed at position zero.')

    jobs_lookup = {job['order_id']: job for job in jobs}
    simulation_clock = F(0)
    witness_records = []

    for position_index, order_id in enumerate(sequence):
        current_job = jobs_lookup[order_id]
        directed_pair = (
            (jobs_lookup[sequence[position_index - 1]]['product_id'], current_job['product_id'])
            if position_index > 0
            else None
        )

        if position_index > 0 and directed_pair not in setup_by_pair:
            raise ValueError(f'Transition edge missing from explicit setup matrix: {directed_pair}')

        applied_setup = (
            rational(setup_by_pair[directed_pair]) if position_index > 0 else rational(s0)
        )
        if applied_setup < 0:
            raise ValueError('Negative setup duration encountered in transition matrix.')

        job_production_seconds = rational(current_job['production_seconds'])
        setup_start_epoch = simulation_clock
        simulation_clock += applied_setup + job_production_seconds

        witness_records.append({
            'position': position_index + 1,
            'order_id': order_id,
            'alias': current_job['alias'],
            'setup_start_seconds': float(setup_start_epoch),
            'setup_seconds': float(applied_setup),
            'production_seconds': float(job_production_seconds),
            'completion_seconds': float(simulation_clock)
        })

    return witness_records