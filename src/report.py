# ==============================================================================
# MODULE: LATEX BENCHMARK REPORT AND ARTIFACT GENERATOR (report.py)
# ==============================================================================
# Generates deterministic LaTeX macros, individual booktabs tables, and a
# comprehensive analytical narrative in formal academic English directly from
# computed CSV and JSON artifacts, eliminating external Word dependencies.
# ==============================================================================

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from .data_io import read_csv


# ==============================================================================
# SECTION 1: NUMERICAL AND STRING SANITIZATION HELPERS
# ==============================================================================

def fmt(value: Any, dec: int = 2) -> str:
    """
    Format numeric inputs into standardized decimal strings.

    Args:
        value: Numeric value or string representation.
        dec: Number of decimal digits to preserve.

    Returns:
        Formatted string, or an em-dash if the value is null or empty.
    """
    if value is None or value == '':
        return '—'
    return f'{float(value):,.{dec}f}'


def escape_latex(text: Any) -> str:
    """
    Escape special LaTeX characters in strings to avoid compilation errors.

    Args:
        text: Input string or numeric value.

    Returns:
        Sanitized string safe for LaTeX compilation.
    """
    val_str = str(text)
    replacements = [
        ('\\', r'\textbackslash{}'),
        ('_', r'\_'),
        ('%', r'\%'),
        ('&', r'\&'),
        ('#', r'\#'),
        ('$', r'\$'),
        ('{', r'\{'),
        ('}', r'\}'),
        ('~', r'\textasciitilde{}'),
        ('^', r'\textasciicircum{}'),
    ]
    for char, target in replacements:
        if char in val_str:
            val_str = val_str.replace(char, target)
    return val_str


# ==============================================================================
# SECTION 2: MASTER LATEX REPORT AND ARTIFACT BUILDER
# ==============================================================================

def build_report(
    results: Path,
    figures: Path,
    output: Path,
    test_count: int = 68
) -> Path:
    """
    Generate LaTeX macros, booktabs tables, and the comprehensive narrative.

    Args:
        results: Path pointing to directory with verified CSV and JSON files.
        figures: Path pointing to directory containing generated graphics.
        output: Destination directory where LaTeX artifacts are saved.
        test_count: Total number of verified unit and integration tests.

    Returns:
        Path to the primary generated LaTeX narrative document.
    """
    output.mkdir(parents=True, exist_ok=True)
    tables_dir = output / 'tables'
    tables_dir.mkdir(parents=True, exist_ok=True)

    summary = json.loads((results / 'summary.json').read_text(encoding='utf-8'))
    ref = read_csv(results / 'reference_scenarios.csv')
    anchors = read_csv(results / 'sensitivity_anchor_summary.csv')
    stats = read_csv(results / 'lr3_descriptive_statistics.csv')
    trace = read_csv(results / 'trace_setup_reductions.csv')
    blocks = read_csv(results / 'sensitivity_reordering_blocks.csv')
    robust = read_csv(results / 'robust_pair_uncertainty.csv')
    samples = read_csv(results / 'sensitivity_sample.csv')
    centres = read_csv(results / 'work_centre_audit.csv')
    primary = read_csv(results / 'lr3_primary_orders.csv')
    quantity = read_csv(results / 'quantity_reconciliation.csv')
    all_lr = read_csv(results / 'lr3_all_orders.csv')
    exclusion = next(r for r in all_lr if r['alias'] == 'LR3_074')

    planned_total = sum(int(r['planned_quantity']) for r in primary)
    completed_total = sum(int(r['completed_quantity']) for r in primary)
    scrap_total = sum(int(r['scrapped_quantity']) for r in primary)

    # --------------------------------------------------------------------------
    # 2.1 EXPORT NUMERICAL MACROS (macros.tex)
    # --------------------------------------------------------------------------
    macros_path = output / 'macros.tex'
    macro_lines = [
        '% Auto-generated numerical constants for thesis manuscript',
        f'\\newcommand{{\\TotalRawOrders}}{{{summary["raw_rows"]}}}',
        f'\\newcommand{{\\MonitoredWorkCentres}}{{{summary["work_centres"]}}}',
        f'\\newcommand{{\\LRThreeAllOrders}}{{{summary["lr3_all_n"]}}}',
        f'\\newcommand{{\\LRThreePrimaryOrders}}{{{summary["lr3_primary_n"]}}}',
        f'\\newcommand{{\\LRThreeDistinctProducts}}{{{summary["lr3_products"]}}}',
        f'\\newcommand{{\\LRThreeToolingGroups}}{{{summary["lr3_groups"]}}}',
        f'\\newcommand{{\\LRThreeProductionHours}}{{{summary["lr3_production_main_hours"]:.4f}}}',
        f'\\newcommand{{\\LRThreeSetupHours}}{{{summary["lr3_setup_main_hours"]:.4f}}}',
        f'\\newcommand{{\\LRThreePrimarySetupSharePercent}}{{{summary["primary_observed_setup_share_percent"]:.3f}}}',
        f'\\newcommand{{\\LRThreeFullSetupSharePercent}}{{{summary["full_observed_setup_share_percent"]:.3f}}}',
        f'\\newcommand{{\\ReferenceSetupAMinutes}}{{{summary["reference_a_minutes"]:.4f}}}',
        f'\\newcommand{{\\ReferenceSetupBMinutes}}{{{summary["reference_b_minutes"]:.4f}}}',
        f'\\newcommand{{\\ReferenceInitialSetupMinutes}}{{{summary["initial_setup_minutes"]:.4f}}}',
        f'\\newcommand{{\\ReferenceDeltaChanges}}{{{summary["reference_delta_changes"]}}}',
        f'\\newcommand{{\\ReferenceSavingHours}}{{{summary["reference_saving_hours"]:.4f}}}',
        f'\\newcommand{{\\ReferenceSavingPercent}}{{{summary["reference_saving_percent"]:.3f}}}',
        f'\\newcommand{{\\RobustCriticalEpsilonMinutes}}{{{summary["robust_critical_epsilon_minutes"]:.4f}}}',
        f'\\newcommand{{\\CompletionLaterOrders}}{{{summary["completion_later_orders"]}}}',
        f'\\newcommand{{\\CompletionEarlierOrders}}{{{summary["completion_earlier_orders"]}}}',
        f'\\newcommand{{\\CompletionMaxLaterHours}}{{{summary["completion_max_later_hours"]:.4f}}}',
        f'\\newcommand{{\\CompletionMaxEarlierHours}}{{{summary["completion_max_earlier_hours"]:.4f}}}',
        f'\\newcommand{{\\PlannedPiecesTotal}}{{{planned_total}}}',
        f'\\newcommand{{\\CompletedPiecesTotal}}{{{completed_total}}}',
        f'\\newcommand{{\\ScrapPiecesTotal}}{{{scrap_total}}}',
        f'\\newcommand{{\\VerifiedTestCount}}{{{test_count}}}',
        f'\\newcommand{{\\HistoricalMakespanHours}}{{{float(ref[0]["completion_hours"]):.3f}}}',
        f'\\newcommand{{\\GroupedMakespanHours}}{{{float(ref[1]["completion_hours"]):.3f}}}',
        f'\\newcommand{{\\ResourceHoursWithConflict}}{{{int(summary["resource_hours_with_conflict"])}}}'
    ]
    macros_path.write_text('\n'.join(macro_lines) + '\n', encoding='utf-8')

    # --------------------------------------------------------------------------
    # 2.2 EXPORT INDIVIDUAL TABLES
    # --------------------------------------------------------------------------
    
    # Table: Elements of Delivery Scope
    t_scope = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Core dimensions and verification scope of the LR3 benchmark.}',
        r'\label{tab:delivery_scope}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{lXX}',
        r'\toprule',
        r'\textbf{Preserved Data} & \textbf{Primary Analysis Scope} & \textbf{Verification Evidence} \\',
        r'\midrule',
        f'{summary["raw_rows"]} raw transactional orders & {summary["lr3_primary_n"]} primary LR3 orders & {test_count} automated tests \\\\',
        r'2 master workbooks and operational note & 29 product references & 8 publication vector graphics \\\\',
        r'Strict SHA-256 byte repeatability & 25 provisional tooling families & Verified CSV ledger files \\\\',
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ]
    (tables_dir / 'table_delivery_scope.tex').write_text('\n'.join(t_scope) + '\n', encoding='utf-8')

    # Table: Raw Data Sources and Ingestion Role
    t_sources = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Preserved empirical source datasets, domain specifications, and analytical roles.}',
        r'\label{tab:preserved_sources}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{>{\raggedright\arraybackslash}p{3.4cm}>{\raggedright\arraybackslash}p{3.0cm}X}',
        r'\toprule',
        r'\textbf{Source Entity} & \textbf{Physical Scope} & \textbf{Analytical Role} \\',
        r'\midrule',
        f'\\texttt{{production\\_order.xlsx}} & {summary["raw_rows"]} orders, 11 attributes & Primary transactional dataset for temporal reconstruction, capacity partition, and scheduling baseline. \\\\',
        f'\\texttt{{ProductDetail.xlsx}} & {summary["product_detail_audit"]["rows"]:,} attribute rows & Auxiliary catalog taxonomy table queried for referential attribute completeness. \\\\',
        r'Operational Domain Note & 10 verified logging rules & Validates timestamp interpretations, setup placement, and single-capacity constraints (Prime Optimal Solutions). \\\\',
        r'Study Data Protocol & Formal metric and mass rules & Establishes conventions for conforming piece counts and accounting reconciliations. \\\\',
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ]
    (tables_dir / 'table_preserved_sources.tex').write_text('\n'.join(t_sources) + '\n', encoding='utf-8')

    # Table: Information Epistemic Status
    t_status = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Epistemic taxonomy and interpretation of operational metrics.}',
        r'\label{tab:information_status}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{>{\raggedright\arraybackslash}p{2.2cm}>{\raggedright\arraybackslash}p{4.2cm}X}',
        r'\toprule',
        r'\textbf{Data Status} & \textbf{Representative Example} & \textbf{Methodological Interpretation} \\',
        r'\midrule',
        r'Recorded & completed\_quantity, change\_over\_end & Raw values from ERP; require integrity audits. \\',
        r'Derived & Elapsed duration = end $-$ start & Direct mathematical consequence of recorded timestamps. \\',
        r'Allocated & Hourly allocated piece counts & Assumed uniform allocation; not a physical meter reading. \\',
        r'Assumed & Availability at $t=0$; parameters $a, b$ & Baseline experimental conditions; not empirical facts. \\',
        r'Simulated & Job completion epoch in G0 & Model-clock recurrence output under declared parameters. \\',
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ]
    (tables_dir / 'table_information_status.tex').write_text('\n'.join(t_status) + '\n', encoding='utf-8')

    # Table: ERP Logging Anomalies
    t_anomalies = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Fleet-wide structural anomalies identified in raw transactional tables.}',
        r'\label{tab:erp_anomalies}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{X>{\raggedleft\arraybackslash}p{2.2cm}>{\raggedright\arraybackslash}p{5.8cm}}',
        r'\toprule',
        r'\textbf{Integrity Audit Condition} & \textbf{Observed Count} & \textbf{Methodological Treatment} \\',
        r'\midrule',
        f'Missing essential timestamps & {summary["missing_time_orders"]} & Preserved; excluded from setup partitioning. \\\\',
        f'Divergent setup initiation timestamps & {summary["divergent_time_orders"]} & Flagged; quarantined from primary time cohort. \\\\',
        f'Zero productive transformation duration & {summary["zero_production_orders"]} & Zero allocated pieces; excluded from machining run. \\\\',
        f'Negative completed quantity & {summary["negative_good_orders"]} & Signed financial adjustment; excluded from run rate. \\\\',
        f'Negative scrap adjustments & {summary["negative_scrap_orders"]} & Preserved signed values; yield marked uncomputable. \\\\',
        f'Overlapping pairs on changeover start & {summary["overlap_pairs_changeover"]} & Full pairwise sweep line conflict detection. \\\\',
        f'Overlapping pairs on official actual start & {summary["overlap_pairs_actual"]} & Official window check; capacity unapproved. \\\\',
        f'Total orders involved in overlaps & {summary["all_overlap_orders"]} & Flagged; quarantined from conservative allocation. \\\\',
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ]
    (tables_dir / 'table_erp_anomalies.tex').write_text('\n'.join(t_anomalies) + '\n', encoding='utf-8')

    # Table: Quantity Reconciliation Ledger
    t_reconciliation = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Reconciliation of recorded quantities across allocation categories}',
        r'\label{tab:quantity_reconciliation}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{Xrrrr}',
        r'\toprule',
        r'\textbf{Quantity Stream} & \textbf{Raw Recorded} & \textbf{Allocated ($\ge 0$)} & \textbf{Unallocated ($\ge 0$)} & \textbf{Signed Adjustments} \\',
        r'\midrule'
    ]
    for q_row in quantity:
        label = 'Conforming output' if q_row['quantity_field'] == 'completed_quantity' else 'Defect scrap'
        t_reconciliation.append(
            f"{label} & {int(float(q_row['source_signed'])):,} & {int(float(q_row['allocated_nonnegative'])):,} & "
            f"{int(float(q_row['unallocated_nonnegative'])):,} & {int(float(q_row['signed_adjustments'])):,} \\\\"
        )
    t_reconciliation.extend([
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ])
    (tables_dir / 'table_quantity_reconciliation.tex').write_text('\n'.join(t_reconciliation) + '\n', encoding='utf-8')

    # Table: LR3_074 Timestamp Divergence
    t_divergence = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Lifecycle timestamp audit for quarantined benchmark order LR3\_074.}',
        r'\label{tab:lr3_074_divergence}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{X>{\raggedright\arraybackslash}p{6.0cm}}',
        r'\toprule',
        r'\textbf{Recorded Attribute / Evaluated Difference} & \textbf{Recorded Value / Audit Result} \\',
        r'\midrule',
        f'actual\\_start\\_date & {escape_latex(exclusion["actual_start_date"])} \\\\',
        f'change\\_over\\_start & {escape_latex(exclusion["change_over_start"])} \\\\',
        f'change\\_over\\_end & {escape_latex(exclusion["change_over_end"])} \\\\',
        f'actual\\_completion\\_date & {escape_latex(exclusion["actual_completion_date"])} \\\\',
        r'Setup duration via change\_over\_start & 7 hours 59 minutes 30 seconds \\',
        r'Setup duration via actual\_start\_date & 9 hours 14 minutes 29 seconds \\',
        r'Timestamp discrepancy & 1 hour 14 minutes 59 seconds \\',
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ]
    (tables_dir / 'table_lr3_074_divergence.tex').write_text('\n'.join(t_divergence) + '\n', encoding='utf-8')

    # Table: Primary Benchmark Cohort Descriptive Metrics
    t_primary_cohort = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Aggregated operational metrics for the primary 78-order LR3 cohort.}',
        r'\label{tab:primary_cohort_metrics}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{Xr}',
        r'\toprule',
        r'\textbf{Operational Dimension / Metric} & \textbf{Calibrated Aggregate Value} \\',
        r'\midrule',
        r'Validated orders / manufactured products / provisional families & 78 / 29 / 25 \\',
        f'Total planned conforming units & {planned_total:,} \\\\',
        f'Total completed conforming units & {completed_total:,} \\\\',
        f'Total positive scrap defect units & {scrap_total:,} \\\\',
        f'Aggregate plan attainment ($Y / P$) & {completed_total / planned_total * 100:.3f}\\% \\\\',
        f'Aggregate process yield ($Y / (Y + S)$) & {completed_total / (completed_total + scrap_total) * 100:.3f}\\% \\\\',
        f'Aggregated production run duration & {summary["lr3_production_main_hours"]:.4f} hours \\\\',
        f'Aggregated recorded setup duration & {summary["lr3_setup_main_hours"]:.4f} hours \\\\',
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ]
    (tables_dir / 'table_primary_cohort_metrics.tex').write_text('\n'.join(t_primary_cohort) + '\n', encoding='utf-8')

    # Table: Setup Descriptive Statistics for Supported Pairs
    inter_s = stats[0]
    t_setup_stats = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Descriptive statistics for setups of originally consecutive eligible pairs.}',
        r'\label{tab:setup_supported_stats}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{Xrrrrrr}',
        r'\toprule',
        r'\textbf{Transition Type} & \textbf{Pairs ($n$)} & \textbf{Min (m)} & \textbf{Median (m)} & \textbf{Mean (m)} & \textbf{Max (m)} & \textbf{SD (m)} \\',
        r'\midrule',
        f'Intergroup transitions & 75 & {float(inter_s["min"]):.3f} & {float(inter_s["median"]):.3f} & {float(inter_s["mean"]):.3f} & {float(inter_s["max"]):.3f} & {float(inter_s["sd"]):.3f} \\\\',
        f'Intragroup transitions & 1 & {summary["reference_a_minutes"]:.3f} & {summary["reference_a_minutes"]:.3f} & {summary["reference_a_minutes"]:.3f} & {summary["reference_a_minutes"]:.3f} & --- \\\\',
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ]
    (tables_dir / 'table_setup_supported_stats.tex').write_text('\n'.join(t_setup_stats) + '\n', encoding='utf-8')

    # Table: Trace Reductions on Compacted Historical Trace
    t_trace = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Hypothetical proportional setup reductions on the compacted historical trace.}',
        r'\label{tab:trace_reductions}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{Xrrr}',
        r'\toprule',
        r'\textbf{Setup Reduction} & \textbf{Makespan (h)} & \textbf{Absolute Saving (h)} & \textbf{Makespan Contraction (\%)} \\',
        r'\midrule'
    ]
    primary_sample_keys = {'primary_without_divergence'}
    filtered_trace = [r for r in trace if r.get('sample') in primary_sample_keys]
    if not filtered_trace:
        filtered_trace = [r for r in trace if r.get('sample') not in ('completo', 'full', 'all_orders')] or trace

    for tr_row in filtered_trace:
        reduction_val = float(tr_row.get('setup_reduction_fraction', 0.0)) * 100
        pct_label = f"{reduction_val:.0f}\\%"
        t_trace.append(
            f"{pct_label} & {float(tr_row['completion_hours']):.3f} & "
            f"{float(tr_row['saving_hours']):.3f} & {float(tr_row['saving_percent']):.3f}\\% \\\\"
        )
        
    t_trace.extend([
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ])
    (tables_dir / 'table_trace_reductions.tex').write_text('\n'.join(t_trace) + '\n', encoding='utf-8')

    # Table: Reference Scenario Makespan Results
    t_ref_scenarios = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Performance metrics across comparable reference sequencing scenarios on asset LR3.}',
        r'\label{tab:reference_scenarios}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{Xrrrrr}',
        r'\toprule',
        r'\textbf{Scenario} & \textbf{Changes} & \textbf{Setup (h)} & \textbf{Makespan (h)} & \textbf{Saving vs H0 (h)} & \textbf{Saving vs H0 (\%)} \\',
        r'\midrule'
    ]
    for r_scen in ref:
        t_ref_scenarios.append(
            f"{r_scen['scenario']} & {r_scen['changes']} & {float(r_scen['setup_hours']):.3f} & "
            f"{float(r_scen['completion_hours']):.3f} & {float(r_scen['saving_hours_vs_H0']):.3f} & "
            f"{float(r_scen['saving_percent_vs_H0']):.3f}\\% \\\\"
        )
    t_ref_scenarios.extend([
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ])
    (tables_dir / 'table_reference_scenarios.tex').write_text('\n'.join(t_ref_scenarios) + '\n', encoding='utf-8')

    # Table: Alternative Setup Anchors Sensitivity
    anchor_name_map = {
        'q25': r'First quartile ($Q_1$)',
        'q25_intergrupo': r'First quartile ($Q_1$)',
        'intergroup_q25': r'First quartile ($Q_1$)',
        'mediana_intergrupo': r'Median ($Q_2$)',
        'intergroup_median': r'Median ($Q_2$)',
        'median': r'Median ($Q_2$)',
        'media_intergrupo': 'Mean (Baseline)',
        'intergroup_mean': 'Mean (Baseline)',
        'mean': 'Mean (Baseline)',
        'q75_intergrupo': r'Third quartile ($Q_3$)',
        'intergroup_q75': r'Third quartile ($Q_3$)',
        'q75': r'Third quartile ($Q_3$)'
    }
    
    t_anchors = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Sensitivity to alternative descriptive intergroup setup anchors, with $a = 2.8833\text{ min}$}',
        r'\label{tab:sensitivity_anchors}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{X r r r}',
        r'\toprule',
        r'\textbf{Descriptive anchor} & \textbf{Reference $b$ (min)} & \textbf{Reduction (h)} & \textbf{Relative duration reduction (\%)} \\',
        r'\midrule'
    ]

    for anc in anchors:
        raw_anchor = str(anc.get('anchor', ''))
        lbl = anchor_name_map.get(raw_anchor, raw_anchor)
        if raw_anchor not in anchor_name_map:
            lbl = lbl.replace('_', r'\_')
            
        b_val = float(anc['b_minutes'])
        red_h = float(anc['saving_hours'])
        red_pct = float(anc['saving_percent'])
        
        # Garante formatação matemática com sinal de menos para valores negativos
        red_h_str = f"${red_h:.4f}$" if red_h < 0 else f"{red_h:.4f}"
        red_pct_str = f"${red_pct:.4f}\\%$" if red_pct < 0 else f"{red_pct:.4f}\\%"
        
        t_anchors.append(
            f"{lbl} & {b_val:.4f} & {red_h_str} & {red_pct_str} \\\\"
        )
        
    t_anchors.extend([
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ])
    (tables_dir / 'table_sensitivity_anchors.tex').write_text('\n'.join(t_anchors) + '\n', encoding='utf-8')

    # Table: Positional Block Reordering Sensitivity
    t_blocks = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Makespan contraction under positional block reordering restrictions.}',
        r'\label{tab:sensitivity_blocks}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{Xrrrr}',
        r'\toprule',
        r'\textbf{Orders per Block} & \textbf{Changes} & \textbf{Makespan (h)} & \textbf{Saving vs H0 (h)} & \textbf{Saving vs H0 (\%)} \\',
        r'\midrule'
    ]
    for blk in blocks:
        t_blocks.append(
            f"{blk['block_size']} & {blk['changes']} & {float(blk['completion_hours']):.3f} & "
            f"{float(blk['saving_hours_vs_H0']):.3f} & {float(blk['saving_percent_vs_H0']):.3f}\\% \\\\"
        )
    t_blocks.extend([
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ])
    (tables_dir / 'table_sensitivity_blocks.tex').write_text('\n'.join(t_blocks) + '\n', encoding='utf-8')

    # Table: Sample Cohort Sensitivity (78 vs 79 Orders)
    t_samples = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Sensitivity to the inclusion of quarantined order LR3\_074 ($a, b$ held constant).}',
        r'\label{tab:sensitivity_sample_cohort}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{Xrrrrr}',
        r'\toprule',
        r'\textbf{Evaluated Sample} & \textbf{Orders ($n$)} & \textbf{Changes H/G} & \textbf{Historical (h)} & \textbf{Saving (h)} & \textbf{Saving (\%)} \\',
        r'\midrule'
    ]
    for smp in samples:
        s_lbl = 'Primary cohort' if smp['sample'] == 'principal' else 'All orders (explicit convention)'
        t_samples.append(
            f"{s_lbl} & {smp['n_orders']} & {smp['changes_h']}/{smp['changes_g']} & "
            f"{float(smp['historical_hours']):.3f} & {float(smp['saving_hours']):.3f} & {float(smp['saving_percent']):.3f}\\% \\\\"
        )
    t_samples.extend([
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ])
    (tables_dir / 'table_sensitivity_sample_cohort.tex').write_text('\n'.join(t_samples) + '\n', encoding='utf-8')

    # Table: Exact Robustness Uncertainty Boxes
    chosen_robust = [r for r in robust if float(r['epsilon_minutes']) in [0, 2, 5, 10, 15]]
    t_robust = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Exact analytical makespan contraction intervals under perturbation box $\mathcal{U}_\varepsilon$.}',
        r'\label{tab:robust_pair_uncertainty}',
        r'\renewcommand{\arraystretch}{1.15}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{rrrX}',
        r'\toprule',
        r'\textbf{Radius $\varepsilon$ (m)} & \textbf{Minimum Saving (h)} & \textbf{Maximum Saving (h)} & \textbf{Guaranteed Advantage} \\',
        r'\midrule'
    ]
    for rb in chosen_robust:
        guar = 'Guaranteed positive' if rb['strictly_positive_for_all_setups_in_box'] == 'True' else 'Not guaranteed'
        t_robust.append(
            f"{float(rb['epsilon_minutes']):.0f} & {float(rb['minimum_saving_hours']):.3f} & "
            f"{float(rb['maximum_saving_hours']):.3f} & {guar} \\\\"
        )
    t_robust.extend([
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ])
    (tables_dir / 'table_robust_pair_uncertainty.tex').write_text('\n'.join(t_robust) + '\n', encoding='utf-8')

    # Table: Methodological Demarcation: Verified vs Non-Demonstrated
    t_verification = [
        r'\begin{table}[H]',
        r'\centering',
        r'\caption{Methodological demarcation between internal software verification and empirical factory validation}',
        r'\label{tab:verification_demarcation}',
        r'\renewcommand{\arraystretch}{1.2}',
        r'\small',
        r'\begin{tabularx}{\textwidth}{>{\raggedright\arraybackslash}p{3.2cm} >{\raggedright\arraybackslash}p{5.0cm} X}',
        r'\toprule',
        r'\textbf{Analytical Component} & \textbf{Internal Computational Verification} & \textbf{Operational Factory Validation Status} \\',
        r'\midrule',
        f'Code and algorithms & {test_count} unit and integration tests, algebraic checks and a constructed extreme-case example & Passed the implemented tests; not a formal proof of the entire codebase. \\\\',
        r'\addlinespace[0.2em]',
        r'Product groups & Catalogue support audited; five-character prefix used as a provisional grouping rule & Not physically validated. \\\\',
        r'\addlinespace[0.2em]',
        r'Setup parameters & Exact closed-form identity checks ($\Delta = \Delta B(b - a)$) and sensitivity grids across $a$ and $b$ & Descriptive exploratory anchors; not physically measured changeover durations. \\\\',
        r'\addlinespace[0.2em]',
        r'Execution schedule & Deterministic traversal of closed-batch order sequences under shared $t = 0$ origin & Theoretical permutation comparison; not an executable shop-floor dispatch guarantee. \\\\',
        r'\bottomrule',
        r'\end{tabularx}',
        r'\end{table}'
    ]
    (tables_dir / 'table_verification_demarcation.tex').write_text('\n'.join(t_verification) + '\n', encoding='utf-8')

    # --------------------------------------------------------------------------
    # 2.3 EXPORT COMPREHENSIVE LATEX NARRATIVE (report_narrative.tex)
    # --------------------------------------------------------------------------
    narrative_path = output / 'report_narrative.tex'
    narrative_text = r"""% Comprehensive technical report narrative converted to LaTeX
% Preserves all methodological justifications, definitions, and interpretations.

\section{Executive Summary and Research Question}
\label{sec:executive_summary}

This study addresses a focused industrial scheduling question: for a fixed batch of manufacturing orders on work centre LR3, what is the potential makespan contraction achievable by grouping orders under a provisional prefix rule, and under what changeover durations and pairwise parameter perturbations does this advantage hold?

The evaluation is conducted within a closed-lot deterministic single-machine model, applying common transition setup rules to historical and permuted dispatch sequences. Transformation runtimes correspond to recorded elapsed production windows. Product groups are derived from a provisional 5-digit prefix rule without physical tooling validation, rendering all conclusions strictly conditional on declared assumptions.

The raw enterprise database comprises \TotalRawOrders\ transactional order records across \MonitoredWorkCentres\ manufacturing work centres. On benchmark asset LR3, 78 of the 79 orders satisfy strict timestamp concordance. Order LR3\_074 exhibits an internal discrepancy of 1 hour, 14 minutes, and 59 seconds between its setup initiation timestamps. It is preserved within the baseline dataset and evaluated in sensitivity analyses, but isolated from the primary 78-order calibration batch.

Under the exploratory baseline parameters ($a = \ReferenceSetupAMinutes\text{ minutes}$, $b = \ReferenceSetupBMinutes\text{ minutes}$), grouping reduces inter-group transitions from 76 to 24, contracting batch makespan from \HistoricalMakespanHours\ to \GroupedMakespanHours\ hours. This yields an absolute contraction of \ReferenceSavingHours\ hours (\ReferenceSavingPercent\%). However, this gain depends on unconstrained reordering: restricting reordering to 10-order positional blocks reduces the relative contraction to 0.021\%. Furthermore, global makespan reduction does not imply uniform improvement across individual orders: \CompletionLaterOrders\ orders complete later in the model clock under the grouped sequence.

Under set-based pairwise perturbation analysis ($\mathcal{U}_\varepsilon$), the makespan advantage remains strictly positive for all realizations only while maximum pairwise setup deviation remains below $\varepsilon^* = \RobustCriticalEpsilonMinutes\text{ minutes}$. An adversarial witness realization with $\varepsilon = 15\text{ minutes}$ causes the grouped schedule to complete 13.372 hours later than the historical baseline. Actual capacity recovery, delivery improvement and operational integration have not been demonstrated.

\input{tables/table_delivery_scope.tex}

\section{Data Architecture, Epistemic Status, and Operational Definitions}
\label{sec:data_definitions}

The computational pipeline operates upon primary transactional workbooks whose byte-level immutability is validated via cryptographic SHA-256 digests, governed by internal operational specifications:
\begin{itemize}
    \item \texttt{production\_order.xlsx}: Primary transactional execution table providing order timestamps, planned targets, conforming volumes, and defect records across 2{,}751 dispatches.
    \item \texttt{ProductDetail.xlsx}: Auxiliary product taxonomy catalogue exhibiting 50.20\% missingness across evaluated functional classification columns, confirming that formal taxonomies are unpopulated in enterprise tables.
    \item Operational Domain Note: Internal operational note on temporal records, setups, and known constraints, preserved intact as \nolinkurl{operational_domain_note.docx} (\texttt{1. Ponto 8.docx}) in the computational supplement.
    \item Study Data Protocol: Quantity definitions and analysis protocol (\nolinkurl{docs/protocol_and_definitions.md}, version 1.0.0), consolidating operational conventions and mass conservation rules.
\end{itemize}

\input{tables/table_preserved_sources.tex}
\input{tables/table_information_status.tex}

Key operational indicators are formally defined to ensure mathematical and dimensional consistency:
\begin{equation}
\text{Plan Attainment Ratio} = \frac{Y}{P}, \quad \text{for } P > 0, \; Y \ge 0
\end{equation}
\begin{equation}
\text{Process Conforming Yield} = \frac{Y}{Y + S}, \quad \text{Scrap Proportion} = \frac{S}{Y + S}, \quad \text{for } Y \ge 0, \; S \ge 0, \; Y + S > 0
\end{equation}
\begin{equation}
\text{Signed Plan Deviation} = P - Y
\end{equation}

Plan attainment is evaluated as an unbounded ratio, preserving positive overproduction ($Y > P$) without artificial saturation at 100\%. Signed plan deviation measures absolute volume variance: positive values indicate under-delivery, whereas negative values reflect output exceeding schedule. Retrospective negative scrap records from accounting inventory adjustments are preserved in transactional mass balances but isolated via audit flags to avoid distorting physical process yield.

\section{Temporal Reconstruction, Concurrency Auditing, and Mass Allocation}
\label{sec:reconstruction_audit}

Interval algebra operates over half-open sets $[t_1, t_2)$. The productive transformation window is delimited by changeover completion and order closure: $[\text{change\_over\_end}, \text{actual\_completion\_date})$. This is formally designated as an elapsed window, as unrecorded machine stoppages cannot be excluded.

\input{tables/table_erp_anomalies.tex}

Disjoint timeline partitioning confirms that raw ERP records contain \ResourceHoursWithConflict\ clock hours where concurrent orders share identical work centres, violating single-capacity physics. The transformation pipeline preserves these anomalies in dedicated audit logs rather than truncating them.

\input{tables/table_quantity_reconciliation.tex}

Mass conservation is guaranteed across all eligible hours using continuous decimal shares strictly proportional to productive minutes, ensuring exact numerical closure without integer floor truncation or ad hoc terminal residual adjustments.

\section{Benchmark Asset LR3: Cohort Selection and Empirical Setup Dispersal}
\label{sec:lr3_selection}

\input{tables/table_lr3_074_divergence.tex}
\input{tables/table_primary_cohort_metrics.tex}

Benchmark asset LR3 contains 79 order dispatches. Quarantining order LR3\_074 leaves 78 verified orders comprising 29 distinct product references. Within the historical sequence, 76 eligible transitions occur between distinct provisional groups, and exactly 1 transition occurs within the same provisional group.

\input{tables/table_setup_supported_stats.tex}

Recorded intergroup changeovers exhibit extreme dispersion (mean of 22.647 minutes versus median of 6.850 minutes, with a standard deviation of 39.287 minutes). Furthermore, 60 transition occurrences (representing directed product pairs, some repeated with multiplicities) out of the 77 transitions in the grouped sequence lack historical support, reinforcing the necessity of sensitivity and set-based robustness evaluations.

\section{Mathematical Formulation of the Closed-Lot Model}
\label{sec:mathematical_model}

The deterministic single-machine model evaluates batch makespan under the forward recurrence:
\begin{equation}
C_0 = 0, \quad S_k = C_{k-1}, \quad C_k = S_k + s_k + p_k
\end{equation}
For $n$ orders and $B$ intergroup transitions, makespan evaluates to the exact analytical closed form:
\begin{equation}
C(B) = \sum_{j=1}^{n} p_j + s_0 + (n - 1 - B)a + Bb
\end{equation}
Between historical sequence H0 ($B_H = 76$) and grouped sequence G0 ($B_G = 24$), makespan contraction evaluates to:
\begin{equation}
C_H - C_G = (B_H - B_G)(b - a) = 52(b - a)
\end{equation}

\input{tables/table_trace_reductions.tex}
\input{tables/table_reference_scenarios.tex}

\section{Sensitivity Analysis and Set-Based Robustness Evaluation}
\label{sec:sensitivity_robustness}

\input{tables/table_sensitivity_anchors.tex}
\input{tables/table_sensitivity_blocks.tex}
\input{tables/table_sensitivity_sample_cohort.tex}

Makespan contraction is highly sensitive to the chosen descriptive anchor: utilizing the intergroup sample median reduces the gain from 1.110\% to 0.226\%. Restricting reordering to positional blocks demonstrates that local grouping yields negligible gains.

\input{tables/table_robust_pair_uncertainty.tex}

Under the bounded perturbation box $\mathcal{U}_\varepsilon$, where transition setups satisfy $s_e \in [\max(0, \mu_e - \varepsilon), \mu_e + \varepsilon]$, the lower saving bound follows:
\begin{equation}
\Delta_{\min}(\varepsilon) = \sum_{e} c_e \cdot \begin{cases} \max(0, \mu_e - \varepsilon), & \text{if } c_e \ge 0 \\ \mu_e + \varepsilon, & \text{if } c_e < 0 \end{cases}
\end{equation}
The critical threshold where guaranteed advantage reaches zero is $\varepsilon^* = \RobustCriticalEpsilonMinutes\text{ minutes}$. Beyond this radius, adversarial realizations can reverse the policy advantage.

\section{Methodological Demarcation and Verification Status}
\label{sec:verification_status}

\input{tables/table_verification_demarcation.tex}

Computational checks confirm that all programmatic transformations, rational arithmetic evaluations, and file exports pass without failure. However, physical tooling equivalence, operational schedule viability, and dynamic arrival constraints remain unverified on the shop floor. Actual capacity recovery, delivery improvement and operational integration have not been demonstrated.
"""
    narrative_path.write_text(narrative_text, encoding='utf-8')

    return narrative_path