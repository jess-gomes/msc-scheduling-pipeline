# ==============================================================================
# MODULE: PURE TEMPORAL OPERATIONS AND HALF-OPEN INTERVALS (temporal.py)
# ==============================================================================
# Provides deterministic mathematical primitives for continuous time intervals,
# disjoint timeline partitioning, pairwise overlap detection, and exact decimal
# allocation across hourly calendar windows.
# ==============================================================================

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Iterable

from .data_io import HOUR_US, US, iso

# ==============================================================================
# SECTION 1: CANONICAL STATE LABELS
# ==============================================================================

# Exact state string tokens required by downstream analysis and unit test suites
STATE_IDLE = 'no_recorded_activity'
STATE_CONFLICT = 'conflict'
STATE_DEFAULT_ORDER = 'order'


# ==============================================================================
# SECTION 2: INTERVAL DATA STRUCTURE DEFINITION
# ==============================================================================

@dataclass(frozen=True)
class Interval:
    """
    Immutable representation of a half-open temporal interval [start, end).

    Attributes:
        order_id: Alphanumeric identifier of the associated production order.
        centre: Identifier of the monitored manufacturing work centre.
        start: Start timestamp in microseconds since Unix epoch (inclusive).
        end: End timestamp in microseconds since Unix epoch (exclusive).
        state: Categorical activity label assigned to this execution segment.
        issue: Boolean flag indicating whether the record has a temporal anomaly.
    """
    order_id: str
    centre: str
    start: int
    end: int
    state: str = STATE_DEFAULT_ORDER
    issue: bool = False

    def __post_init__(self) -> None:
        """
        Validate temporal ordering upon instance creation.

        Raises:
            ValueError: If the end boundary strictly precedes the start boundary.
        """
        if self.end < self.start:
            raise ValueError('End timestamp cannot precede start timestamp in interval.')


# ==============================================================================
# SECTION 3: PAIRWISE OVERLAP DETECTION AND INTERSECTION METRICS
# ==============================================================================

def overlap(interval_a: Interval, interval_b: Interval) -> int:
    """
    Compute the temporal intersection duration between two intervals on the same asset.

    Args:
        interval_a: First half-open temporal interval.
        interval_b: Second half-open temporal interval.

    Returns:
        Intersection duration in microseconds, or zero if assets differ or intervals are disjoint.
    """
    if interval_a.centre != interval_b.centre:
        return 0
    intersection_start = max(interval_a.start, interval_b.start)
    intersection_end = min(interval_a.end, interval_b.end)
    return max(0, intersection_end - intersection_start)


def all_pairs(intervals: Iterable[Interval]) -> list[dict]:
    """
    Identify all overlapping pairs of production intervals on identical assets.

    Evaluates potential overlaps per work centre using a sweep line approach.
    Sorted sweeps break early once a subsequent interval starts after the current end boundary.

    Args:
        intervals: Iterable collection of Interval objects.

    Returns:
        List of dictionaries detailing pairwise overlap metadata and duration.
    """
    grouped_by_centre: defaultdict[str, list[Interval]] = defaultdict(list)
    for current_interval in intervals:
        grouped_by_centre[current_interval.centre].append(current_interval)

    detected_overlaps: list[dict] = []

    for centre_key, centre_intervals in sorted(grouped_by_centre.items()):
        # Sort intervals by start epoch, end epoch, and order identifier
        centre_intervals.sort(key=lambda item: (item.start, item.end, item.order_id))
        total_intervals = len(centre_intervals)

        for primary_index, primary_interval in enumerate(centre_intervals):
            for candidate_index in range(primary_index + 1, total_intervals):
                candidate_interval = centre_intervals[candidate_index]

                # Chronological sorting guarantees subsequent intervals will not overlap
                if candidate_interval.start >= primary_interval.end:
                    break

                overlap_microseconds = overlap(primary_interval, candidate_interval)
                if overlap_microseconds > 0 and primary_interval.order_id != candidate_interval.order_id:
                    overlap_start_us = max(primary_interval.start, candidate_interval.start)
                    overlap_end_us = min(primary_interval.end, candidate_interval.end)

                    detected_overlaps.append({
                        'work_centre': centre_key,
                        'order_a': primary_interval.order_id,
                        'order_b': candidate_interval.order_id,
                        'overlap_start': iso(overlap_start_us),
                        'overlap_end': iso(overlap_end_us),
                        'overlap_seconds': overlap_microseconds / US
                    })

    return detected_overlaps


# ==============================================================================
# SECTION 4: TIMELINE PARTITIONING AND STATE SEGMENTATION
# ==============================================================================

def partition(
    intervals: Iterable[Interval],
    start: int,
    end: int,
    centre: str
) -> list[dict]:
    """
    Partition a continuous observation window into disjoint operational state segments.

    Extracts timeline events across active intervals, classifying each contiguous segment
    into an operational state: unoccupied idle time, single-order processing, or concurrency conflict.
    Overlapping runtimes are not summed as additive machine occupancy.

    Args:
        intervals: Iterable collection of Interval objects to partition.
        start: Start timestamp of the partition window in microseconds.
        end: End timestamp of the partition window in microseconds.
        centre: Identifier of the target manufacturing work centre.

    Returns:
        List of dictionaries defining consecutive disjoint state intervals.

    Raises:
        ValueError: If partition window boundaries are invalid (end <= start).
    """
    if end <= start:
        raise ValueError('Partition observation window is empty or inverted.')

    timeline_events: defaultdict[int, dict[str, list[tuple[int, Interval]]]] = defaultdict(
        lambda: {'end': [], 'start': []}
    )

    # Anchor boundary timestamps
    timeline_events[start]
    timeline_events[end]

    for interval_index, current_interval in enumerate(intervals):
        if current_interval.centre != centre:
            continue

        clipped_start = max(start, current_interval.start)
        clipped_end = min(end, current_interval.end)

        if clipped_end > clipped_start:
            timeline_events[clipped_start]['start'].append((interval_index, current_interval))
            timeline_events[clipped_end]['end'].append((interval_index, current_interval))

    sorted_event_timestamps = sorted(timeline_events.keys())
    active_intervals_map: dict[int, Interval] = {}
    partition_segments: list[dict] = []

    for current_idx, current_epoch in enumerate(sorted_event_timestamps[:-1]):
        # Expire intervals ending at this epoch
        for interval_key, _ in timeline_events[current_epoch]['end']:
            active_intervals_map.pop(interval_key, None)

        # Register intervals starting at this epoch
        for interval_key, interval_instance in timeline_events[current_epoch]['start']:
            active_intervals_map[interval_key] = interval_instance

        next_epoch = sorted_event_timestamps[current_idx + 1]
        if next_epoch == current_epoch:
            continue

        distinct_order_ids = sorted(
            set(active_item.order_id for active_item in active_intervals_map.values())
        )
        active_count = len(active_intervals_map)

        if active_count == 0:
            segment_state = STATE_IDLE
        elif active_count > 1:
            segment_state = STATE_CONFLICT
        else:
            segment_state = next(iter(active_intervals_map.values())).state

        segment_duration_seconds = (next_epoch - current_epoch) / US
        has_temporal_issue = any(
            active_item.issue for active_item in active_intervals_map.values()
        )

        partition_segments.append({
            'work_centre': centre,
            'start_us': current_epoch,
            'end_us': next_epoch,
            'start': iso(current_epoch),
            'end': iso(next_epoch),
            'seconds': segment_duration_seconds,
            'state': segment_state,
            'n_active': active_count,
            'order_ids': distinct_order_ids,
            'temporal_issue': has_temporal_issue
        })

    return partition_segments


# ==============================================================================
# SECTION 5: HOURLY DISCRETIZATION AND MASS CONSERVATION
# ==============================================================================

def hour_parts(start: int, end: int) -> list[tuple[int, int]]:
    """
    Decompose a continuous interval [start, end) into hourly calendar windows.

    Args:
        start: Interval start timestamp in microseconds.
        end: Interval end timestamp in microseconds.

    Returns:
        List of tuples: (clock_hour_start_us, duration_within_hour_us).

    Raises:
        ValueError: If the end timestamp strictly precedes the start timestamp.
    """
    if end < start:
        raise ValueError('Cannot decompose inverted interval into hourly parts.')

    decomposed_parts: list[tuple[int, int]] = []
    current_cursor = start

    while current_cursor < end:
        clock_hour_floor = (current_cursor // HOUR_US) * HOUR_US
        clock_hour_ceiling = min(end, clock_hour_floor + HOUR_US)
        segment_duration_us = clock_hour_ceiling - current_cursor

        decomposed_parts.append((clock_hour_floor, segment_duration_us))
        current_cursor = clock_hour_ceiling

    return decomposed_parts


def uniform_allocation(
    total_quantity: int,
    start: int,
    end: int
) -> list[tuple[int, int, Decimal]]:
    """
    Allocate unit counts proportionally across decomposed hourly intervals under uniform assumption.

    Enforces exact decimal conservation: intermediate hourly portions are quantized
    to 12 decimal places, and any cumulative residual is assigned to the terminal hour partition.

    Args:
        total_quantity: Total integer unit volume to allocate.
        start: Execution start timestamp in microseconds.
        end: Execution end timestamp in microseconds.

    Returns:
        List of tuples: (clock_hour_start_us, duration_in_hour_us, allocated_decimal_quantity).

    Raises:
        ValueError: If total_quantity is negative or duration is non-positive.
        ArithmeticError: If rounding residual generates a negative allocation.
    """
    if total_quantity < 0:
        raise ValueError('Negative quantity cannot be allocated across operational windows.')
    if end <= start:
        raise ValueError('Cannot allocate production volume across non-positive duration.')

    hourly_segments = hour_parts(start, end)
    allocation_results: list[tuple[int, int, Decimal]] = []
    accumulated_allocated = Decimal(0)
    total_duration_us = Decimal(end - start)
    total_units_decimal = Decimal(total_quantity)

    with localcontext() as precision_context:
        precision_context.prec = 40

        for segment_index, (hour_start_epoch, duration_us) in enumerate(hourly_segments):
            is_last_segment = (segment_index == len(hourly_segments) - 1)

            if not is_last_segment:
                proportional_fraction = Decimal(duration_us) / total_duration_us
                allocated_units = (total_units_decimal * proportional_fraction).quantize(
                    Decimal('0.000000000001')
                )
            else:
                # Terminal hour absorbs exact residual to preserve conservation
                allocated_units = total_units_decimal - accumulated_allocated

            if allocated_units < 0:
                raise ArithmeticError('Negative allocation detected due to rounding discrepancy.')

            allocation_results.append((hour_start_epoch, duration_us, allocated_units))
            accumulated_allocated += allocated_units

    return allocation_results