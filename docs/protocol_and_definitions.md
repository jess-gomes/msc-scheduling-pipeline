# Methodological Protocol, Operational Definitions, and Experimental Decisions

## 1. Provenance and Scope of Operational Definitions

The primary data architecture preserves two raw Excel workbooks and the accompanying operational note without modification. The supervisory definitions established during project orientation specify that completed_quantity represents conforming output strictly excluding defect scrap, whereas planned_quantity represents target conforming piece volume. This operational distinction is not inferred from column labels, but grounded in supervisory domain instruction.

The operational note establishes that setup duration belongs to the initiating manufacturing order, that setup initiation and actual execution start timestamps coincide across standard records, and that completion dates record operational batch closure in shop-floor logs. The interval between change_over_end and actual_completion_date defines an elapsed transformation window, as unrecorded machine stoppages cannot be excluded. The source system contains no records of production calendars, order release epochs, shift schedules, or asset-level parallel execution capacity.

## 2. Research Question

For a fixed manufacturing batch on asset LR3, quantify the potential makespan contraction achievable by grouping orders under a provisional prefix rule with a homogeneous setup structure; determine how this contraction behaves across alternative descriptive setup anchors, unobserved directed product transitions, and restricted positional reordering windows.

This formulation constitutes a conditional, offline deterministic experiment. It does not represent an operational shop-floor digital twin or a predictive dispatching engine.

## 3. Immutable Governance Rules

1. **Immutability of Identifiers and Physical Quantities:** Preserve all raw identifiers and reported values. Convert Excel serial timestamps into civil timestamps without forcing artificial time zones. Normalize serialization noise situated within a tolerance of 0.001 seconds (1 millisecond) of integer second boundaries, maintaining 64-bit integer microseconds as internal storage. Intermediate rounding to minute precision is prohibited.
2. **Dual Initiation Timestamp Concurrency Audit:** Audit all pairwise combinations across each work centre using both change_over_start and actual_start_date. Formalize operational windows as half-open intervals $[t_1, t_2)$. Publish both audit sets independently; distinguish pairwise conflict counts, distinct involved orders, and unique conflict hours.
3. **Disjoint Resource Timeline Partitioning:** Partition asset timelines between official bounding dates into mutually exclusive states: setup, production window, indeterminate state, concurrency conflict, and unrecorded activity. Disjoint partitioning provides mathematical coverage without proving active physical machine utilization.
4. **Conservative Temporal Eligibility Criteria:** Quarantine orders failing strict validation: missing timestamps, divergent setup initiation dates, negative setups, non-positive productive durations, or involvement in concurrency conflicts under either convention. This segregation constitutes an explicit calibration filter, not an assertion that excluded dispatches are physically impossible.
5. **Continuous Decimal Mass Balance and Hourly Conservation:** Allocate non-negative unit counts across productive hours strictly for temporally eligible orders using continuous decimal shares proportional to productive duration. No integer floor truncation or ad hoc terminal residual adjustments are applied. Conforming output and scrap are reconciled independently. Negative records represent signed accounting adjustments; lacking explicit counter-entries, they are never converted into physical production through sign inversion or truncation.
6. **Formulation of Performance Indicators:**
   - Plan attainment: $Y / P$, valid for $P > 0$ and non-negative counts.
   - Process yield: $Y / (Y + S)$ and scrap fraction: $S / (Y + S)$, valid for $Y, S \ge 0$ and $Y + S > 0$.
   - Conforming plan difference: $P - Y$.
   - Global metrics evaluate as ratios of cohort sums, never as unweighted averages of order ratios.
7. **Primary Benchmark Cohort Selection on Asset LR3:** Establish the primary calibration batch at 78 orders. The exclusion of order LR3_074 results strictly from its 1-hour 15-minute setup start divergence, not its long duration. The complete 79-order sequence is preserved and evaluated in sensitivity analyses.
8. **Provisional Taxonomic Grouping Heuristic:** Define product groups by the five-character item code prefix exclusively as an exploratory baseline. The auxiliary ProductDetail catalog is audited without relational cross-joins; prefix grouping is not asserted as verified physical tool or die compatibility.
9. **Descriptive Setup Calibration on Observed Adjacencies:** Derive empirical setup parameters strictly from originally consecutive pairs where both orders satisfy temporal eligibility: 76 intergroup transitions and 1 intragroup transition. Adjacencies generated by removing quarantined dispatches are not treated as observed empirical transitions.
10. **Closed-Lot Single-Machine Paradigm:** Enforce batch availability at $t = 0$ as an experimental boundary condition. Retain recorded productive runtimes, historical initial job assignment, and boundary setup $s_0$ across all compared dispatch sequences. Shifting historical production durations to alternative sequence positions is a strong experimental assumption unvalidated against shop-floor dynamics.
11. **Provisional Group Sequence Construction:** Construct grouped dispatch sequences by group first-appearance priority, preserving internal historical arrival order within each group. The homogeneous model applies setup $a$ within groups and setup $b$ across groups identically to historical sequence H0 and grouped sequence G0. Scenarios H20 and G20 scale inter-order setups by a factor of 0.8 while holding boundary setup $s_0$ invariant.
12. **Separation of Compacted Trace from Sequence Models:** Maintain clear separation between the compacted historical trace with recorded individual setups and the common sequence model. Eliminating idle intervals during trace compaction represents a geometric abstraction, not a policy-derived operational saving.
13. **Multidimensional Sensitivity Protocols:** Systematically vary descriptive setup anchors, $(a/b, b)$ parameter grids, positional reordering blocks, the inclusion of divergent order LR3_074, and individual SKU grouping rules. The proportion of favorable parameter combinations must never be interpreted as an empirical probability of success.
14. **Set-Based Robustness on Directed Transitions:** Evaluate parameter perturbation box $\mathcal{U}_\varepsilon$ where each directed product pair $e = (i, j)$ satisfies $s_e \in [\max(0, \mu_e - \varepsilon), \mu_e + \varepsilon]$. Identical directed pairs assume identical setup durations across compared schedules. Lower and upper makespan bounds represent exact analytical extrema over the perturbation box, not statistical confidence intervals. The perturbation radius $\varepsilon$ is unvalidated against factory operations.
15. **Job-Level Completion Shifts:** Evaluate order completion epoch displacements strictly from the common origin in model clock time. Displacements represent structural schedule shifts, not delivery delays against commercial due dates.

## 4. Programmatic Execution Invariants

The computational pipeline strictly halts upon encountering schema ambiguities, duplicated primary keys, unparsed Excel formula tags, non-positive processing runtimes, invalid sequence permutations, or violations of temporal and mass conservation identities.

Global data anomalies and concurrency failures are retained in audit tables and marked as FAILED in the validation ledger. Programmatic verification passes when all calculations match exact mathematical definitions, regardless of whether underlying ERP source data contain operational logging flaws.

## 5. Empirical Boundaries and Technical Limitations

Available data are sufficient to substantiate the offline conditional benchmark and maintain byte-level reproducibility without auxiliary undocumented inputs.

Available records remain insufficient to identify all unobserved pairwise changeovers, validate physical tooling compatibility, guarantee historical schedule feasibility, isolate active processing speeds from recorded elapsed windows, optimize commercial due dates, or evaluate capital investment return. None of these unobserved dimensions is artificially populated or assumed.