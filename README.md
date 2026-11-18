# Sales Compensation Calculation Engine: Case Study

> A portfolio write-up of a data product I designed and built at a Fortune 10 healthcare company, plus a **runnable demo engine written from scratch on synthetic data**.
> No company code, data, file layouts or business rules are included. The write-up stays at the design level, and the demo reproduces the architecture using made-up people, deals and payout rules.

**Role:** Sole developer: design, implementation, testing and documentation
**Stack:** Python, pandas, Excel/openpyxl, pytest, Azure Functions (HTTP trigger), SharePoint, Git/GitHub (PR-based workflow), Power Automate (planned)
**Timeframe:** _[fill in]_

---

## Run the demo

```bash
pip install -r requirements.txt
python -m comp_engine demo --through 2025-09
python -m pytest -q
```

`demo` generates a seeded synthetic dataset in `data/input/`. It then runs each month from April (start of the fiscal year) through the month you choose, approving and locking every period except the last. Each month's output package is written to `data/output/<month>/`.

The synthetic data is built to exercise every rule:

| Employee | Scenario it demonstrates |
|---|---|
| E006 | Over-performer climbing the progressive payout curve |
| E007 | Front-loaded sales: YTD attainment falls, producing **negative carryforward** instead of negative pay |
| E008 | New hire whose **guarantee** lifts amount due to the floor, with the uplift tracked separately |
| E009 | Not incentive-eligible: excluded with a QC **warning** |
| E002 / E006 | One-off **SPIFF** paid only in its month |
| E003 → E004 | September **credit override**: every product-line row of the deal moves before rollups |
| M01 / M02 | **Manager rollups** reconciled against direct reports |

Other commands: `python -m comp_engine generate`, `run --month YYYY-MM`, `lock --month YYYY-MM`. Re-running a locked month, or running a month whose prior period is not locked, fails validation.

### Demo code map

```
comp_engine/
  contract.py   input classes, required columns, PASS/WARNING/FAIL report
  fiscal.py     April-March fiscal calendar
  pipeline.py   weighted pipeline + opportunity-owner summary
  sales.py      monthly/YTD sales, manager rollups, reconciliation
  payout.py     payout curve, SPIFFs, carryforward, guarantees
  state.py      governed prior-period state (save / lock / load)
  manifest.py   SHA-256 run manifest
  engine.py     end-to-end run and output package (CSV, Excel, JSON)
  synthetic.py  seeded synthetic data generator
tests/          28 unit and end-to-end tests
```

---

## The problem

Every month, the Sales Compensation team prepared incentive payouts by hand across many spreadsheets. Business users uploaded a full set of input files each cycle, even when most of them hadn't changed. Analysts then rebuilt sales totals, applied quotas and payout curves, and reconciled manager rollups manually.

That led to:
- a lot of repeated work each cycle
- results that were hard to audit or reproduce
- errors from manual overrides being applied twice or not at all
- no clear way to grow toward self-service or AI-assisted explanations of payouts

## What I built (original project)

As the only developer on the project, I built a **deterministic Python calculation engine** that turns raw CRM bookings data plus a small set of reference files into an approved, auditable payout package.

### 1. A minimal-input contract
I sorted every input into one of four classes so the business only provides what actually changed:

| Class | Example | Business effort |
|---|---|---|
| Recurring source | Monthly CRM bookings export | Every month |
| Reusable reference | Roster, quotas, incentive terms | Only when something changes |
| Exception input | Approved adjustments and credit overrides | Only when one applies |
| Engine-derived | Fiscal YTD sales, pipeline summaries | Never: computed from source |

This removed several manual uploads from the monthly cycle.

### 2. Validation and run gating
- Checks that required inputs are present before processing, and lets optional exception files be absent
- Treats duplicate or missing files as blocking errors and unexpected files as QC warnings
- Checks that the reporting month and fiscal year are consistent
- Central **PASS / WARNING / FAIL** summary: a run stops only on FAIL

### 3. Calculation logic
- **Fiscal-period sales:** monthly and YTD totals built from booking close dates on a non-calendar fiscal year
- **Weighted pipeline** at product-line grain: closed-won at full value, open stages weighted by normalized probability (accepts `60` or `0.60`), invalid probabilities rejected
- **Payouts:** quota attainment, a progressive payout curve, cumulative incentive and paid-to-date tracking
- **Bonuses and guarantees:** one-off bonus programs and new-hire minimum guarantees, each kept in its own column so it can be audited
- **Negative carryforward:** negative earnings are carried forward to offset future payouts instead of producing negative payroll, with opening, applied and ending balances tracked
- **Manager rollups:** built from the reporting hierarchy, reconciled against direct-report totals, and kept from double counting contributor totals
- **Override handling:** credit reassignments are applied before rollups, and validation stops the same correction from also being entered as a manual adjustment

### 4. Auditable output package
Each run produces:
- a detailed payout CSV covering sales, attainment, bonuses, carryforward, guarantees and amount due
- a pipeline-detail CSV
- a business-facing Excel workbook in the layout the team already used, showing only results the engine produced
- a **JSON run manifest** with run metadata and **SHA-256 hashes of every input and output**, so any payout can be traced back to its exact source files

### 5. Governed prior-period state
- Once a period is approved, the state it hands to the next period is **locked**: carryforward balances, paid-to-date and cumulative incentive
- Later runs read the locked prior-period state rather than recomputing history, so approved payouts can't drift
- The reporting period is configurable, so any month can be run or re-run on purpose

### 6. Cloud-ready interfaces
- An **Azure Functions HTTP adapter** wraps the engine, so it runs the same way locally (`python -m ...`) and as a cloud endpoint
- Written **I/O contracts** for SharePoint intake and Azure cloud storage define exactly which files are expected, where they live and how outputs are written back
- Optional file staging, plus a storage boundary layer that keeps the calculation code separate from where the files are stored

### 7. Engineering practices
- Python owns every calculation: deterministic, testable and versioned
- Feature-branch and pull-request workflow, with 60+ commits of incremental, reviewed changes
- Automated tests cover the runner, the input contract, rollups, pipeline weighting, bonuses, payouts, guarantees and carryforward
- Data handling: inputs and outputs are excluded from version control, and the repo holds only code, tests, templates and docs

## Architecture

```
CRM bookings + reference files
        │
        ▼
  Input contract & validation  ──► PASS / WARNING / FAIL
        │
        ▼
  Python calculation engine (sales → pipeline → payouts → rollups)
        │
        ▼
  Approved output package (CSV + Excel + hashed JSON manifest)
        │                         │
        ▼                         ▼
  Locked prior-period state   (Planned) AI assistant that answers
  feeds the next run          payout questions from approved results

  Entry points: local CLI  |  Azure Function HTTP adapter
  Storage:      local dirs |  SharePoint / Azure (via storage boundary)
```

### Repository layout (original project)

```
src/        calculation engine, input contract, validation, storage boundary
tests/      automated tests for each calculation and validation area
scripts/    operational scripts, including prior-period state locking
docs/       architecture and target-state diagrams
data/       local input/output folders (git-ignored; no real data committed)
function_app.py                 Azure Functions HTTP adapter
SHAREPOINT_INTAKE_CONTRACT.md   intake specification
AZURE_CLOUD_IO_CONTRACT.md      cloud I/O specification
```

## Roadmap I designed
- Full SharePoint and Azure deployment with automatic reuse of the latest approved reference files (intake and I/O contracts already written)
- Power Automate orchestration calling the Azure Function endpoint
- An AI assistant that explains each employee's payout, grounded only in approved engine output
- Expanding the framework to more business units, each with its own sources and rules

## Impact
- **Less monthly work for the business:** the routine monthly upload went from a full set of workbooks to essentially one CRM bookings export. Roster, goals and incentive terms are reused until they change, and fiscal-YTD sales and opportunity-owner summaries are no longer uploaded at all because the engine derives them.
- **Spreadsheet rebuilds replaced by one command:** sales totals, attainment, payout curves, SPIFFs, guarantees, carryforward and manager rollups now come from a single deterministic run instead of manual workbook steps.
- **Audit-ready by default:** every payout can be traced to the exact input files through SHA-256 hashed run manifests, and approved months are locked so history can't change silently.
- **Errors caught before payout:** missing or duplicate files, invalid probabilities, unknown owners and rollup mismatches surface as PASS / WARNING / FAIL results instead of being found after payroll.
- **Foundation for scale:** cloud entry points and written intake contracts mean more business units, and an AI assistant, can plug into the same approved outputs.

## What I learned
Most of the value came from designing the input contract around how business users actually work, not from the calculations. Asking people for less and deriving the rest removed both effort and a whole class of errors. I also learned to put AI on top of a deterministic, tested core instead of inside it: compensation has to be explainable and reproducible, so the engine owns the numbers and any assistant only explains approved results. And building auditability in from day one, with hashes, locked periods and explicit validation, made the system much easier to trust and to change.
