# ==============================================================================
# MODULE: VISUAL FIGURE GENERATION (figures.py)
# ==============================================================================
# Renders publication-quality vector and raster graphics derived strictly from
# computed tabular CSV artifacts. Enforces one self-contained plot per figure
# without hardcoded color palettes, relying on standard Matplotlib cycle defaults.
# ==============================================================================

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .data_io import read_csv


# ==============================================================================
# SECTION 1: MASTER FIGURE GENERATION PIPELINE
# ==============================================================================

def create_figures(results_dir: Path, output_dir: Path) -> list[Path]:
    """
    Generate all analytical dissertation figures from reconciled CSV and JSON artifacts.

    Exports both PNG and SVG formats per figure, formatted for direct integration
    into LaTeX documents and technical Word reports.

    Args:
        results_dir: Path to directory containing audited CSV and summary.json files.
        output_dir: Destination directory where rendered graphics will be saved.

    Returns:
        List of Path instances pointing to all generated image files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_data = json.loads((results_dir / 'summary.json').read_text(encoding='utf-8'))
    generated_filepaths: list[Path] = []

    def save_figure(figure_instance: plt.Figure, base_filename: str) -> None:
        """Persist figure canvas to disk in PNG and SVG formats with tight bounding boxes."""
        figure_instance.tight_layout(pad=1.4)
        for extension in ['png', 'svg']:
            target_path = output_dir / f'{base_filename}.{extension}'
            figure_instance.savefig(target_path, dpi=180, bbox_inches='tight')
            generated_filepaths.append(target_path)
        plt.close(figure_instance)

    # --------------------------------------------------------------------------
    # FIGURE 1: RECORDED ELAPSED PRODUCTION WINDOWS AND OUTLIER ISOLATION
    # --------------------------------------------------------------------------
    all_orders_data = read_csv(results_dir / 'lr3_all_orders.csv')
    fig1, ax1 = plt.subplots(figsize=(8.0, 4.4))

    cohort_styles = [
        ('True', 'o', f'Primary cohort ({summary_data["lr3_primary_n"]})'),
        ('False', 'x', f'Outside primary cohort ({summary_data["lr3_all_n"] - summary_data["lr3_primary_n"]})')
    ]

    for is_primary_str, marker_symbol, legend_label in cohort_styles:
        cohort_points = [
            (int(row['alias'].split('_')[1]), float(row['production_seconds']) / 3600)
            for row in all_orders_data
            if str(row.get('primary_lr3')).strip() == is_primary_str
        ]
        ax1.scatter(
            [pt[0] for pt in cohort_points],
            [pt[1] for pt in cohort_points],
            marker=marker_symbol,
            s=32,
            label=legend_label
        )

    ax1.set_yscale('log')
    ax1.set_xlabel('Position in Full Historical LR3 Sequence')
    ax1.set_ylabel('Production Window Duration (Hours, Log Scale)')
    ax1.set_title('Recorded Windows: Elapsed Duration Without Verified Active Run Time', fontsize=11)
    ax1.legend(fontsize=9, loc='lower right')
    ax1.grid(axis='y', alpha=0.25)
    save_figure(fig1, 'fig01_recorded_windows')

    # --------------------------------------------------------------------------
    # FIGURE 2: EMPIRICAL DISTRIBUTION OF OBSERVED INTERGROUP SETUPS
    # --------------------------------------------------------------------------
    transitions_data = read_csv(results_dir / 'lr3_original_transitions.csv')
    intergroup_setup_values = sorted(
        float(row['setup_seconds']) / 60
        for row in transitions_data
        if str(row.get('both_primary')).strip() == 'True' and str(row.get('within_group')).strip() == 'False'
    )

    fig2, ax2 = plt.subplots(figsize=(8.0, 4.4))
    cumulative_probabilities = np.arange(1, len(intergroup_setup_values) + 1) / len(intergroup_setup_values)

    ax2.step(
        intergroup_setup_values,
        cumulative_probabilities,
        where='post',
        label=f'Intergroup: {len(intergroup_setup_values)} transitions'
    )
    ax2.axvline(
        float(np.median(intergroup_setup_values)),
        linestyle='--',
        label=f'Median: {float(np.median(intergroup_setup_values)):.2f} min'
    )
    ax2.axvline(
        summary_data['reference_b_minutes'],
        linestyle=':',
        label=f'Mean: {summary_data["reference_b_minutes"]:.2f} min'
    )

    ax2.set_xscale('log')
    ax2.set_xlabel('Recorded Setup Duration (Minutes, Log Scale)')
    ax2.set_ylabel('Empirical Cumulative Probability')
    ax2.set_ylim(0, 1.04)
    ax2.set_title('Descriptive Variability of Intergroup Setup Durations', fontsize=11)
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.2)
    save_figure(fig2, 'fig02_setup_distribution')

    # --------------------------------------------------------------------------
    # FIGURE 3: SETUP COMPONENT ACROSS REFERENCE BENCHMARK SCENARIOS
    # --------------------------------------------------------------------------
    scenarios_data = read_csv(results_dir / 'reference_scenarios.csv')
    fig3, ax3 = plt.subplots(figsize=(7.8, 4.2))

    scenario_labels = [row['scenario'] for row in scenarios_data]
    setup_hour_values = [float(row['setup_hours']) for row in scenarios_data]

    ax3.bar(scenario_labels, setup_hour_values)
    for bar_idx, setup_val in enumerate(setup_hour_values):
        ax3.text(bar_idx, setup_val + 0.4, f'{setup_val:.2f}', ha='center', fontsize=10)

    ax3.set_ylim(0, max(setup_hour_values) * 1.16)
    ax3.set_ylabel('Model Setup Duration (Hours)')
    ax3.set_xlabel(f'Scenario (Fixed productive duration: {summary_data["lr3_production_main_hours"]:.4f} hours)')
    ax3.set_title('Setup Duration Component Across Benchmark Scenarios', fontsize=11)
    ax3.grid(axis='y', alpha=0.2)
    save_figure(fig3, 'fig03_scenario_setups')

    # --------------------------------------------------------------------------
    # FIGURE 4: MAKESPAN SENSITIVITY ACROSS DESCRIPTIVE SETUP ANCHORS
    # --------------------------------------------------------------------------
    anchors_data = read_csv(results_dir / 'sensitivity_anchor_summary.csv')

    anchor_label_map = {
        'intergroup_q25': '25th Percentile',
        'intergroup_median': 'Median',
        'intergroup_q75': '75th Percentile',
        'intergroup_mean': 'Mean',
        'q25_intergrupo': '25th Percentile',
        'mediana_intergrupo': 'Median',
        'q75_intergrupo': '75th Percentile',
        'media_intergrupo': 'Mean'
    }

    def anchor_sort_key(record: dict) -> int:
        tag = record['anchor']
        if 'q25' in tag:
            return 0
        if 'mediana' in tag or 'median' in tag:
            return 1
        if 'q75' in tag:
            return 2
        return 3

    sorted_anchors = sorted(anchors_data, key=anchor_sort_key)
    fig4, ax4 = plt.subplots(figsize=(7.8, 4.4))

    saving_percentages = [float(row['saving_percent']) for row in sorted_anchors]
    display_labels = [anchor_label_map.get(row['anchor'], row['anchor']) for row in sorted_anchors]

    ax4.bar(display_labels, saving_percentages)
    ax4.axhline(0, linewidth=0.8)

    for bar_idx, percentage_val in enumerate(saving_percentages):
        offset_distance = 6 if percentage_val >= 0 else -16
        ax4.annotate(
            f'{percentage_val:.3f}%',
            (bar_idx, percentage_val),
            xytext=(0, offset_distance),
            textcoords='offset points',
            ha='center',
            fontsize=10
        )

    ax4.set_ylim(-0.12, 1.30)
    ax4.set_ylabel('Makespan Reduction (%)')
    ax4.set_xlabel('Descriptive Anchor for Intergroup Setup Duration')
    ax4.set_title('Makespan Reduction Sensitivity Across Setup Anchors (a = 2.88 min)', fontsize=11)
    ax4.grid(axis='y', alpha=0.2)
    save_figure(fig4, 'fig04_descriptive_anchors')

    # --------------------------------------------------------------------------
    # FIGURE 5: PARAMETER SENSITIVITY OVER HOMOGENEOUS SETUP FUNCTION GRIDS
    # --------------------------------------------------------------------------
    grid_data = read_csv(results_dir / 'sensitivity_grid.csv')
    fig5, ax5 = plt.subplots(figsize=(8.0, 4.6))

    target_ratios = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
    for ratio_value in target_ratios:
        matching_rows = sorted(
            [row for row in grid_data if abs(float(row['a_over_b']) - ratio_value) < 1e-10],
            key=lambda item: float(item['b_minutes'])
        )
        if matching_rows:
            x_minutes = [float(row['b_minutes']) for row in matching_rows]
            y_savings = [float(row['saving_percent']) for row in matching_rows]
            ax5.plot(x_minutes, y_savings, marker='.', label=f'a/b = {ratio_value:g}')

    ax5.axhline(0, linewidth=0.7)
    ax5.set_xlabel('Intergroup Setup Duration b (Minutes)')
    ax5.set_ylabel('Makespan Reduction (%)')
    ax5.set_title('Conditional Sensitivity Across Setup Duration Parameters', fontsize=11)
    ax5.legend(fontsize=9, ncol=2)
    ax5.grid(alpha=0.2)
    save_figure(fig5, 'fig05_parameter_sensitivity')

    # --------------------------------------------------------------------------
    # FIGURE 6: SET-BASED ROBUSTNESS UNDER PAIRWISE SETUP PERTURBATIONS
    # --------------------------------------------------------------------------
    robustness_data = read_csv(results_dir / 'robust_pair_uncertainty.csv')
    x_epsilon = np.array([float(row['epsilon_minutes']) for row in robustness_data])
    lower_bound_savings = np.array([float(row['minimum_saving_hours']) for row in robustness_data])
    upper_bound_savings = np.array([float(row['maximum_saving_hours']) for row in robustness_data])

    fig6, ax6 = plt.subplots(figsize=(8.0, 4.6))
    ax6.fill_between(
        x_epsilon,
        lower_bound_savings,
        upper_bound_savings,
        alpha=0.18,
        label='Feasible domain under uncertainty box'
    )
    ax6.plot(x_epsilon, lower_bound_savings, label='Lower bound')
    ax6.plot(x_epsilon, upper_bound_savings, linestyle='--', label='Upper bound')
    ax6.axhline(0, linewidth=0.8)

    if summary_data.get('robust_critical_epsilon_minutes') is not None:
        crit_eps = summary_data['robust_critical_epsilon_minutes']
        ax6.axvline(
            crit_eps,
            linestyle=':',
            label=f'Critical guarantee limit: {crit_eps:.2f} min'
        )

    ax6.set_xlabel('Maximum Pairwise Perturbation Radius epsilon (Minutes)')
    ax6.set_ylabel('Historical Minus Grouped Makespan (Hours)')
    ax6.set_title('Set-Based Robustness Under Pairwise Setup Perturbations', fontsize=11)
    ax6.legend(fontsize=8, loc='upper left')
    ax6.grid(alpha=0.2)
    save_figure(fig6, 'fig06_pairwise_robustness')

    # --------------------------------------------------------------------------
    # FIGURE 7: CONTRACTION BENEFIT VERSUS POSITIONAL REORDERING WINDOWS
    # --------------------------------------------------------------------------
    block_data = read_csv(results_dir / 'sensitivity_reordering_blocks.csv')
    fig7, ax7 = plt.subplots(figsize=(7.8, 4.2))

    block_labels = [row['block_size'] for row in block_data]
    block_savings = [float(row['saving_percent_vs_H0']) for row in block_data]

    ax7.bar(block_labels, block_savings)
    for bar_idx, saving_val in enumerate(block_savings):
        ax7.text(bar_idx, saving_val + 0.025, f'{saving_val:.3f}%', ha='center', fontsize=10)

    ax7.set_ylim(0, 1.28)
    ax7.set_xlabel(f'Positional Block Size ({summary_data["lr3_primary_n"]} = Global Unconstrained Grouping)')
    ax7.set_ylabel('Makespan Reduction (%)')
    ax7.set_title('Contraction Gain Versus Positional Reordering Window', fontsize=11)
    ax7.grid(axis='y', alpha=0.2)
    save_figure(fig7, 'fig07_reordering_limits')

    # --------------------------------------------------------------------------
    # FIGURE 8: JOB-LEVEL COMPLETION SHIFTS ALONG THE REORDERED SCHEDULE
    # --------------------------------------------------------------------------
    shifts_data = read_csv(results_dir / 'paired_completion_shifts.csv')
    fig8, ax8 = plt.subplots(figsize=(8.0, 4.5))

    x_positions = [int(row['position_h']) for row in shifts_data]
    y_shift_hours = [float(row['shift_g_minus_h_hours']) for row in shifts_data]

    ax8.scatter(x_positions, y_shift_hours, s=26)
    ax8.axhline(0, linewidth=0.9)
    ax8.set_xlabel('Order Position in Primary Historical Sequence')
    ax8.set_ylabel(r'$\delta_j = T_{k_G(j)}(\pi_G) - T_{k_H(j)}(\pi_H)\quad\text{[model hours]}$')
    ax8.set_title('Batch Makespan Contraction Does Not Advance All Order Completions', fontsize=11)

    annotation_text = (
        f'{summary_data["completion_later_orders"]} completing later; '
        f'{summary_data["completion_earlier_orders"]} completing earlier; 1 invariant\n'
        'Model completion shifts, not empirical delivery tardiness.'
    )
    ax8.text(0.02, 0.04, annotation_text, transform=ax8.transAxes, fontsize=9)
    ax8.grid(alpha=0.2)
    save_figure(fig8, 'fig08_completion_shifts')

    return generated_filepaths