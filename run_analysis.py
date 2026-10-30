#!/usr/bin/env python3
# ==============================================================================
# SCRIPT: TABULAR ANALYSIS PIPELINE RUNNER (run_analysis.py)
# ==============================================================================
# Reconstructs and recalculates all tabular benchmark results, state allocations,
# and audit ledgers directly from original XLSX workbooks.
# ==============================================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.analysis import run


# ==============================================================================
# SECTION 1: COMMAND LINE PARSER CONFIGURATION
# ==============================================================================

def build_argument_parser() -> argparse.ArgumentParser:
    """
    Construct the command-line argument parser for the analysis pipeline.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        description=(
            'Reconstruct all tabular benchmark results, state intervals, '
            'and quantity allocation ledgers from original enterprise extracts.'
        )
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Target output directory for calculated artifacts. Defaults to results/.'
    )
    return parser


# ==============================================================================
# SECTION 2: EXECUTION ORCHESTRATION
# ==============================================================================

def main() -> int:
    """
    Orchestrate the end-to-end execution of the tabular analysis pipeline.

    Returns:
        Integer exit code (0 for successful termination).
    """
    argument_parser = build_argument_parser()
    parsed_arguments = argument_parser.parse_args()

    project_root_dir = Path(__file__).resolve().parent
    input_data_dir = project_root_dir / 'input'

    if parsed_arguments.output:
        resolved_output_dir = parsed_arguments.output.resolve()
    else:
        resolved_output_dir = project_root_dir / 'results'

    # Protect raw input files against accidental overwriting
    if resolved_output_dir == input_data_dir or input_data_dir in resolved_output_dir.parents:
        argument_parser.error('Target output directory cannot be set inside the input directory.')

    # Execute analytical pipeline
    execution_summary: dict[str, Any] = run(project_root_dir, resolved_output_dir)

    # Filter key benchmark metrics for terminal inspection
    terminal_report_keys = [
        'raw_rows',
        'lr3_primary_n',
        'lr3_all_n',
        'reference_saving_hours',
        'reference_saving_percent',
        'robust_critical_epsilon_minutes'
    ]
    filtered_summary = {metric_key: execution_summary.get(metric_key) for metric_key in terminal_report_keys}

    print('\n' + '=' * 80)
    print('BENCHMARK PIPELINE EXECUTION SUMMARY')
    print('=' * 80)
    print(json.dumps(filtered_summary, indent=2, ensure_ascii=False))
    print('-' * 80)
    print(f'Destination Directory: {resolved_output_dir}')
    print('=' * 80 + '\n')

    return 0


if __name__ == '__main__':
    sys.exit(main())