# Batch job performance (Milestone 4)

Measured with `python scripts/benchmark_batch.py` on 2026-11-06 (runs between 15:11 and 17:17 UTC). Every number below was measured on the machine described here. Nothing is estimated or extrapolated.

## Machine and software

| | |
|---|---|
| CPU | 11th Gen Intel Core i7-11800H @ 2.30 GHz, 8 cores, 16 threads (laptop) |
| RAM | 15.9 GB |
| OS | Windows 11 Home Single Language, build 26300 (Python's `platform` module reports it as "Windows 10 (10.0.26300)") |
| Storage of files | local SSD (project directory) |
| Python | 3.11.9 |
| Packages | pandas 2.2.3, numpy 2.0.2, pyarrow 26.0.1, xgboost 2.1.3, shap 0.46.0, scikit-learn 1.5.2, SQLAlchemy 2.0.57, psycopg 3.3.8, psutil 7.2.2 |
| SQLite | a fresh database file per run, on the same SSD |
| PostgreSQL | 16 (server 16.15) in a local Docker container (`postgres:16`, port 5433) on the same laptop; its tables were dropped before every run |

The laptop was also running a desktop session (browser, editor) during the runs; no other benchmark or test ran at the same time.

## What was measured

- **Data:** fully synthetic applicants from `loanlens.synthetic` (seeded numpy draws within the model's training ranges; every ID starts with `SYN-`): 100,000 rows (6.8 MB CSV), 500,000 rows (34.2 MB) and 1,000,000 rows (68.3 MB). The files are in `data/benchmarks/` (gitignored). All rows are valid, so every row is scored.
- **Path:** the real job path, end to end. A manager account is created in a fresh database, the CSV is submitted through `services.submit_batch_job` (copied into the private jobs directory) and processed by `worker.work_once`: reading in 20,000-row chunks, validation, scoring with the shared decision core (reasons and "what would change" for every rejected row), audit records in inserts of 1,000 (when on), Parquet and CSV results files, the errors file and the anonymised summary.
- **Wall time:** from submission to the job's completion. Data generation and loading the model are not included. Submission (copying the file) took 0.03 to 0.09 s in every run.
- **Rows per second:** rows in the file divided by wall time.
- **Memory:** resident memory (RSS) of the benchmark process, sampled every 20 ms with psutil. "Start" is after the model was loaded; "growth" is peak minus start.
- **Audit on / off:** `LOANLENS_BATCH_AUDIT=row` (one audit record per row, the default) or `off` (benchmark only; refused in production or hosted mode). Each audit-on run was checked: the audit table held exactly one record per row.
- Each configuration ran once, in its own Python process.

## Results

### SQLite

| Rows | Audit | Wall time | Rows per second | Peak memory | Start memory | Growth |
|---:|---|---:|---:|---:|---:|---:|
| 100,000 | on | 79.3 s | 1,262 | 497 MB | 352 MB | 144 MB |
| 100,000 | off | 70.3 s | 1,423 | 457 MB | 353 MB | 104 MB |
| 500,000 | on | 402.0 s | 1,244 | 517 MB | 352 MB | 165 MB |
| 500,000 | off | 264.4 s | 1,891 | 479 MB | 352 MB | 126 MB |
| 1,000,000 | on | 833.5 s (13.9 min) | 1,200 | 519 MB | 353 MB | 167 MB |
| 1,000,000 | off | 633.3 s (10.6 min) | 1,579 | 483 MB | 353 MB | 130 MB |

### PostgreSQL

| Rows | Audit | Wall time | Rows per second | Peak memory | Start memory | Growth |
|---:|---|---:|---:|---:|---:|---:|
| 100,000 | on | 70.7 s | 1,414 | 498 MB | 359 MB | 139 MB |
| 100,000 | off | 55.7 s | 1,794 | 470 MB | 359 MB | 111 MB |
| 500,000 | on | 344.5 s | 1,451 | 527 MB | 359 MB | 168 MB |
| 500,000 | off | 267.8 s | 1,867 | 489 MB | 360 MB | 130 MB |
| 1,000,000 | on | 663.7 s (11.1 min) | 1,507 | 522 MB | 360 MB | 162 MB |
| 1,000,000 | off | 525.9 s (8.8 min) | 1,902 | 491 MB | 359 MB | 131 MB |

**Excluded run.** The first PostgreSQL 500,000-row audit-off run took 3,281.8 s. The Windows event log shows the laptop went to sleep from 16:00:05 to 16:50:43 UTC, inside that run, so it is not a valid measurement. It was run again at 17:13 UTC with a keep-awake request active (the 267.8 s row above). Every other run finished before the sleep or started after it.

All runs completed with every row scored (for example 577,337 Approved and 422,663 Rejected in the 1,000,000-row file).

## What the numbers say

- **Memory stays flat.** Peak memory was between 457 and 527 MB in every valid run, whether the file had 100,000 or 1,000,000 rows. Growth above the loaded model was 104 to 168 MB, and only 2 MB more at 1,000,000 rows than at 500,000 with audit on (SQLite). The pipeline holds one 20,000-row chunk at a time, so a ten times larger file did not need noticeably more memory. The test suite checks the same property on a 200,000-row file (growth under 200 MB; about 99 MB was measured when the threshold was set).
- **Speed is about 1,200 to 1,900 rows per second** on this laptop, so a 1,000,000-row file took between 8.8 and 13.9 minutes depending on the database and on auditing. The time is spent mostly in scoring and explaining each row (see below), not in reading the file.
- **Auditing every row costs time.** With audit on, 1,000,000 rows took 200 s longer on SQLite (833.5 s against 633.3 s) and 138 s longer on PostgreSQL (663.7 s against 525.9 s). That is the price of writing one permanent record per decision, which the product requires by default.
- **PostgreSQL was faster than SQLite here**, by 20% with audit on at 1,000,000 rows, even though it ran in a container on the same laptop.
- **Run-to-run variation is visible.** Each configuration ran once; for example SQLite without audit gave 1,423 rows per second at 100,000 rows but 1,891 at 500,000. Differences of 10 to 20% between single runs should not be read as real effects.
- **Not measured:** several workers in parallel, a remote database, Linux or a server machine, and Parquet input at these sizes (Parquet input is covered by the tests for correctness, not timed here).

**Where the time goes.** A profile of scoring one 20,000-row synthetic chunk (8,519 of them rejected) on the same laptop took 15.6 s under the profiler: the "what would change" search for rejected rows 6.3 s (it asks the model about candidate CIBIL increases and loan reductions), SHAP contributions 2.2 s, rule evaluation 2.3 s, and the rest model predictions, features and result building. About 60% of the time is therefore explanation work. Reading and validating a file is small by comparison: in a separate measurement, 19,600 rows were parsed and validated in 0.34 s and scored in 8.6 s.

## How to repeat

```bash
python scripts/benchmark_batch.py                                  # all sizes, SQLite and PostgreSQL, audit on and off
python scripts/benchmark_batch.py --sizes 100000 --backends sqlite # one size, one database
```

PostgreSQL runs need `LOANLENS_TEST_POSTGRES_URL` pointing at a disposable database (its LoanLens tables are dropped before every run); without it the script states that PostgreSQL was not measured. Results are appended to `data/benchmarks/results.jsonl`.
