#!/usr/bin/env python3
# ==============================================================================
# SCRIPT: MASTER PIPELINE ORCHESTRATOR (run_pipeline.py)
# ==============================================================================
# Executes tabular data reconstruction, automated unit testing, publication
# figure rendering, and native LaTeX artifact compilation into an isolated
# output directory.
# ==============================================================================

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any


# ==============================================================================
# SECTION 1: COMMAND LINE PARSER CONFIGURATION
# ==============================================================================

def build_argument_parser() -> argparse.ArgumentParser:
    """
    Construct the command-line argument parser for master pipeline execution.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        description=(
            'Execute the end-to-end analytical pipeline: tabular recomputation, '
            'automated test suite, vector figure rendering, and LaTeX artifact compilation.'
        )
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Target output directory for the execution run. Defaults to reexecution/.'
    )
    return parser


# ==============================================================================
# SECTION 2: ENVIRONMENT AND DEPENDENCY VALIDATION
# ==============================================================================

def verify_environment(project_root_dir: Path, target_dir: Path) -> dict[str, str]:
    """
    Verify Python runtime version, package dependencies, and directory constraints.

    Args:
        project_root_dir: Path to the repository root directory.
        target_dir: Target output directory for generated artifacts.

    Returns:
        Dictionary mapping package names to installed version strings.

    Raises:
        RuntimeError: If Python version is incompatible, target exists, target is inside input,
            or required packages are missing.
    """
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or later is required to execute this pipeline.')

    if target_dir.exists():
        raise RuntimeError(
            f'Target directory already exists: {target_dir}. '
            'Specify an unused directory path to prevent accidental overwriting.'
        )

    input_dir = project_root_dir / 'input'
    if target_dir == input_dir or input_dir in target_dir.parents:
        raise RuntimeError('Target output directory cannot be placed inside the input directory.')

    installed_versions: dict[str, str] = {}
    required_packages = ['numpy', 'matplotlib']

    for package_name in required_packages:
        try:
            installed_versions[package_name] = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            raise RuntimeError(
                f'Required package {package_name} is not installed. '
                'Execute: python -m pip install -r requirements.txt'
            )

    return installed_versions


# ==============================================================================
# SECTION 3: MASTER EXECUTION ORCHESTRATOR
# ==============================================================================

def main() -> int:
    """
    Execute all pipeline stages sequentially while recording provenance and audit metadata.

    Returns:
        Integer exit code (0 for success, 1 for failure).
    """
    argument_parser = build_argument_parser()
    parsed_arguments = argument_parser.parse_args()

    project_root_dir = Path(__file__).resolve().parent
    if parsed_arguments.output:
        target_dir = parsed_arguments.output.resolve()
    else:
        target_dir = (project_root_dir / 'reexecution').resolve()

    try:
        package_versions = verify_environment(project_root_dir, target_dir)
    except RuntimeError as validation_error:
        print(f'Configuration error: {validation_error}', file=sys.stderr)
        return 1

    # Deferred imports from local package after path resolution
    from src.analysis import run
    from src.data_io import sha256
    from src.figures import create_figures
    from src.report import build_report

    target_dir.mkdir(parents=True)
    logs_dir = target_dir / 'logs'
    logs_dir.mkdir()

    input_dir = project_root_dir / 'input'
    initial_input_hashes = {
        file_path.name: sha256(file_path)
        for file_path in sorted(input_dir.iterdir())
        if file_path.is_file()
    }

    runtime_metadata: dict[str, Any] = {
        'python_version': sys.version,
        'platform': platform.platform(),
        'package_dependencies': package_versions,
        'input_state_before': initial_input_hashes
    }

    start_timestamp = time.perf_counter()

    try:
        # Stage 1: Recalculate tabular results from original spreadsheets
        print('1/4 — Recalculating tabular results from original Excel workbooks...', flush=True)
        results_dir = target_dir / 'results'
        execution_summary = run(project_root_dir, results_dir)

        # Stage 2: Run automated test suite against recalculated artifacts
        print('2/4 — Executing automated test suite against generated results...', flush=True)
        test_environment = os.environ.copy()
        test_environment['LR3_RESULTS'] = str(results_dir)
        test_environment['PYTHONUTF8'] = '1'

        test_process = subprocess.run(
            [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
            cwd=project_root_dir,
            env=test_environment,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        test_log_output = test_process.stdout + test_process.stderr
        (logs_dir / 'tests.txt').write_text(test_log_output, encoding='utf-8')

        if test_process.returncode != 0:
            raise RuntimeError(
                'Test suite execution failed. Consult logs/tests.txt for error traces. '
                'Downstream figure rendering and LaTeX artifact generation halted.'
            )

        test_count_match = re.search(r'Ran (\d+) tests?', test_log_output)
        if not test_count_match:
            raise RuntimeError('Could not determine total executed test count from test suite output.')

        verified_test_count = int(test_count_match.group(1))
        runtime_metadata['tests_executed'] = verified_test_count

        # Stage 3: Render publication vector and raster figures
        print(f'3/4 — Rendering publication figures ({verified_test_count} tests verified)...', flush=True)
        figures_dir = target_dir / 'figures'
        create_figures(results_dir, figures_dir)

        # Stage 4: Generate LaTeX macros, tables, and narrative
        print('4/4 — Compiling LaTeX macros, tables, and technical narrative...', flush=True)
        latex_output_dir = target_dir / 'latex'
        build_report(results_dir, figures_dir, latex_output_dir, test_count=verified_test_count)

        # Integrity audit: ensure raw inputs remained immutable throughout execution
        final_input_hashes = {
            file_path.name: sha256(file_path)
            for file_path in sorted(input_dir.iterdir())
            if file_path.is_file()
        }
        if final_input_hashes != initial_input_hashes:
            raise RuntimeError('Source input files were modified during pipeline execution.')

        elapsed_duration = time.perf_counter() - start_timestamp
        key_benchmark_metrics = {
            'lr3_primary_n': execution_summary.get('lr3_primary_n'),
            'reference_saving_hours': execution_summary.get('reference_saving_hours'),
            'reference_saving_percent': execution_summary.get('reference_saving_percent'),
            'robust_critical_epsilon_minutes': execution_summary.get('robust_critical_epsilon_minutes')
        }

        runtime_metadata.update({
            'status': 'PASS',
            'input_files_unchanged': True,
            'elapsed_seconds': elapsed_duration,
            'key_results': key_benchmark_metrics,
            'result_file_hashes': {
                file_path.name: sha256(file_path)
                for file_path in sorted(results_dir.iterdir())
                if file_path.is_file()
            }
        })

        print('\n' + '=' * 80)
        print('MASTER PIPELINE EXECUTION COMPLETED SUCCESSFULLY')
        print('=' * 80)
        print(f'Execution Output Directory: {target_dir}')
        print(f'Total Elapsed Duration:     {elapsed_duration:.2f} seconds')
        print(f'Verified Test Battery:      {verified_test_count} passed')
        print(f'Generated LaTeX Artifacts:  {latex_output_dir}')
        print('=' * 80 + '\n')

    except Exception as execution_error:
        elapsed_duration = time.perf_counter() - start_timestamp
        runtime_metadata.update({
            'status': 'FAIL',
            'error': f'{type(execution_error).__name__}: {execution_error}',
            'elapsed_seconds': elapsed_duration
        })
        print(f'\nPipeline execution failed: {execution_error}', file=sys.stderr)
        return 1
    finally:
        runtime_log_path = logs_dir / 'runtime.json'
        runtime_log_path.write_text(
            json.dumps(runtime_metadata, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8'
        )

    return 0


if __name__ == '__main__':
    sys.exit(main())