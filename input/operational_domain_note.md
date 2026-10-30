# Operational Domain Technical Specification

## 1. Context and Baseline Provenance
This technical note consolidates the operational domain conventions and enterprise resource planning (ERP) logging mechanisms confirmed by the company. It formalizes the domain constraints preserved from internal plant documentation (original note 1. Ponto 8.docx).

## 2. Validated Domain Invariants

### 2.1. Operational Timestamp Definitions
- **change_over_start**: Marks the recorded start of the setup and changeover phase preceding transformation. In regular records (such as 78 of the 79 orders on work centre LR3), this timestamp coincides with actual_start_date; isolated divergence instances (such as order LR3_074) are preserved in dedicated anomaly audit logs.
- **change_over_end**: Marks the formal completion of the setup phase and the recorded start of order transformation.
- **actual_start_date**: Recorded changeover initiation in ERP transaction tables.
- **actual_completion_date**: Recorded closure timestamp of the manufacturing batch in the shop-floor tracking system. The interval between change_over_end and actual_completion_date defines an elapsed transformation window, as unrecorded machine stoppages cannot be excluded.

### 2.2. Changeover Allocation Convention
Changeover duration is assigned exclusively to the initiating production order, not to the preceding completed batch.

### 2.3. Operational Closure Convention
The field actual_completion_date represents the operational conclusion of the production order recorded on the shop floor rather than a delayed administrative office settlement.

### 2.4. Accounting Reconciliations in Scrap Quantities
Negative numerical entries in scrapped_quantity represent retrospective inventory adjustments within the ERP system. They do not constitute physical negative defect generation. These records are retained for transactional mass balance but flagged to prevent distortion in physical scrap yield metrics.

### 2.5. Unit of Measurement
All volumetric metrics (planned_quantity, completed_quantity, and scrapped_quantity) share a common physical unit: integer finished piece counts.

### 2.6. Plant Operating Calendars
Formal shift schedules, planned operator rest breaks, weekend shutdowns, and statutory holiday calendars are not recorded in transactional ERP database extracts.

### 2.7. Unlogged Stoppages and Telemetry
Secondary registries documenting breakdown logs, micro-stoppages, or continuous equipment state events are not tracked in external systems for these orders.

### 2.8. Machine Speeds and Auxiliary References
No external equipment speed registry exists for operational runs. Nominal speed attributes from legacy catalogs do not correspond to operational execution logs. MachineId and work_centre designate the exact same asset entity.

### 2.9. Production Planning Priorities
Order release dates, planned due dates, customer priority classes, and dispatching ranks are absent from transactional order headers.

### 2.10. Equipment Capacity and Parallelism
Monitored work centres operate strictly as single-capacity assets without parallel physical line execution. Concurrent order records within identical clock-hour blocks reflect logging overlap or sequential succession, never simultaneous manufacturing.