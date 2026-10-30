# Computational Supplement for Master Dissertation — Work Centre LR3

This repository contains the deterministic analytical pipeline, temporal reconstruction routines, concurrency audits, and closed-lot scheduling benchmarks developed for manufacturing asset LR3.

---

## 1. Directory Structure and Repository Layout

The root directory contains the following layout:

├── config/
│   └── study.json                  # Operational parameters and sensitivity grids
├── input/
│   ├── production_order.xlsx       # Raw transactional order records (2,751 dispatches)
│   ├── ProductDetail.xlsx          # Auxiliary catalogue taxonomy table (50.20% missingness)
│   └── operational_domain_note.docx # Preserved original operational note (1. Ponto 8.docx)
├── results/                        # Canonical reference benchmarks and audit ledgers
├── src/
│   ├── __init__.py
│   ├── data_io.py                  # Standard-library OpenXML parsing and I/O
│   ├── temporal.py                 # Half-open interval algebra and timeline partitioning
│   ├── model.py                    # Deterministic sequencing engine and robustness box
│   ├── analysis.py                 # Cohort segregation, audit, and scenario runner
│   ├── figures.py                  # Publication vector graphic generator
│   └── report.py                   # Direct LaTeX macro, table, and narrative generator
├── tests/
│   ├── __init__.py
│   ├── test_core.py                # 54 unit tests for interval operations and algebra
│   └── test_integration.py         # 14 integration tests for pipeline invariants and ledgers
├── docs/
│   ├── protocol_and_definitions.md   # Methodological rules, definitions, and protocol (v1.0.0)
│   └── independent_reader_check.json # Dual-engine cell verification audit log
├── requirements.txt                # Runtime dependencies (pytest, numpy, matplotlib)
├── run_analysis.py                 # Standalone tabular analysis runner
├── run_pipeline.py                 # Master orchestrator (recomputation, tests, figures, LaTeX)
├── verify_reader.py                # Independent streaming SAX cell audit verifier
└── README.md

---

## 2. Temporal Precision and Computational Invariants

- Normalization Tolerance: Temporal normalization across discontinuous boundary timestamps applies a strict tolerance of 0.001 seconds (1 millisecond). 
- Internal Data Representation: Internal timestamp representation and elapsed duration calculations are maintained strictly in 64-bit integer microseconds (`datetime64[us]`) to prevent cumulative floating-point drift.
- Mass Allocation: Material volume distribution across calendar hours enforces continuous decimal shares proportional to productive minutes. No integer floor truncation or ad hoc terminal adjustments are applied.
- Input Data Auditing: The script `verify_reader.py` verifies all 30,261 worksheet cells from `input/production_order.xlsx` against an independent SAX streaming parser, recording verification timestamp and digest into `docs/independent_reader_check.json`.

---

## 3. Environment Installation

Tabular processing and core mathematical algorithms rely on the Python standard library. Testing and publication figure rendering require pytest, numpy, and matplotlib.

From the project root directory, install required dependencies using Python 3.11 or later:

```bash
python -m pip install -r requirements.txt