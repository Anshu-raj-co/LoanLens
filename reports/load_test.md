# REST API load test (Milestone 4)

Measured on 2026-11-06 between about 17:20 and 18:05 UTC with Locust against the local API. Every number below was measured here; nothing is estimated or extrapolated.

## Set-up

| | |
|---|---|
| Machine | 11th Gen Intel Core i7-11800H @ 2.30 GHz (8 cores, 16 threads), 15.9 GB RAM, Windows 11 Home Single Language build 26300, Python 3.11.9 |
| Server | `uvicorn loanlens.api.app:app` 0.32.1 (FastAPI 0.115.6) on 127.0.0.1, **1 worker process** and, for comparison, **4 worker processes** |
| Database | **SQLite** (a throwaway file) and **PostgreSQL 16.15** (local Docker container `postgres:16` on the same laptop, a disposable database whose tables were dropped first) |
| Load generator | Locust 2.32.4, headless, on the **same laptop** (it competes with the server for CPU) |
| Test file | `tests/load/locustfile.py` |
| Users and duration | 10, 50 and 100 simulated users, all started at once, **60 seconds** each |
| Behaviour | each user signs in once (`POST /v1/auth/login`), keeps its token, then calls `POST /v1/score` with one of the six built-in example applicants chosen at random, waiting 0.5 to 1.5 s between requests |

Two things were done **for the load test only**, as stated in the task:

- **Accounts:** 100 throwaway applicant accounts were created directly through the service layer (`auth.register_applicant`) in the throwaway database before each run. Their random passwords were kept in a temporary file outside the repository, which was deleted when the run ended.
- **Sign-in limits:** `LOANLENS_API_AUTH_LIMIT_PER_CLIENT` and `LOANLENS_API_AUTH_LIMIT_PER_ACCOUNT` were raised to 10,000 through environment variables on the test server, because every simulated user signs in from the same address and the default (10 per address per 60 s) would block them. The defaults in the code were not changed.

**Every score writes an audit record** before the answer is returned, so all latencies below include the audit write, as well as token checking (one account lookup per request) and the decision with its explanation.

## Results (POST /v1/score)

Latencies are Locust's client-side response times in milliseconds (Locust rounds percentiles to two significant figures). Failure rate is failed score requests divided by all score requests. Sign-ins are excluded from the table and reported below it.

### 1 uvicorn worker

| Database | Users | Requests | Requests/s | p50 | p95 | p99 | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| SQLite | 10 | 550 | 9.3 | 61 | 210 | 290 | 0 (0%) |
| SQLite | 50 | 992 | 16.7 | 1,700 | 3,300 | 4,900 | 0 (0%) |
| SQLite | 100 | 1,064 | 17.9 | 4,000 | 6,500 | 8,600 | 0 (0%) |
| PostgreSQL | 10 | 551 | 9.3 | 60 | 140 | 490 | 0 (0%) |
| PostgreSQL | 50 | 1,346 | 22.7 | 1,100 | 1,900 | 2,200 | 0 (0%) |
| PostgreSQL | 100 | 1,259 | 21.3 | 3,400 | 4,100 | 4,500 | 0 (0%) |

### 4 uvicorn workers

| Database | Users | Requests | Requests/s | p50 | p95 | p99 | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| SQLite | 10 | 502 | 8.5 | 51 | 92 | 260 | 0 (0%) |
| SQLite | 50 | 2,366 | 39.9 | 150 | 550 | 1,100 | 0 (0%) |
| SQLite | 100 | 3,059 | 51.5 | 230 | 3,700 | 6,700 | **34 (1.1%)** |
| PostgreSQL | 10 | 566 | 9.6 | 53 | 93 | 330 | 0 (0%) |
| PostgreSQL | 50 | 2,664 | 44.9 | 59 | 160 | 590 | 0 (0%) |
| PostgreSQL | 100 | 4,800 | 81.0 | 93 | 380 | 1,500 | 0 (0%) |

Sign-ins: one per simulated user, all succeeded except 3 of 100 in the SQLite, 4-worker, 100-user run (503). Sign-in latency is high by design (argon2id password hashing): the median was 460 to 870 ms at 10 users and 3.1 to 5.3 s at 100 users, when 100 users sign in at the same moment.

The 37 failures (34 scores and 3 sign-ins) were all **503 "database_unavailable"**. With four processes writing audit records to one SQLite file at the same time, some writes waited longer than SQLite's lock timeout. Because the audit record could not be written, no decision was returned: the intended fail-closed behaviour.

## Observed bottleneck

- **One worker is CPU-bound in a single Python process.** At 10 users, the server's own log (one JSON line per request) shows a median of about 56 ms of server time per score request (SQLite, 1 worker). One process can therefore serve only about 18 such requests a second, which is where the 1-worker runs level off: 16.7 to 17.9 requests/s on SQLite and 21.3 to 22.7 on PostgreSQL. Above that, requests queue inside the server: the median server-side time rose to about 1.5 s at 50 users and 3.5 s at 100 users, and latency grew while throughput stayed flat.
- **More worker processes scale it.** With 4 workers on PostgreSQL, throughput rose to 81 requests/s at 100 users with p50 93 ms and no failures. That is close to what 100 users with a 0.5 to 1.5 s pause can request (roughly 100 a second at most).
- **SQLite becomes the limit with several processes.** With 4 workers, SQLite reached 51.5 requests/s but its p95 rose to 3.7 s and 1.1% of requests failed on the write lock. PostgreSQL handled the same load without failures.
- At **10 users** no configuration was saturated: every run served what the users asked for (about 9 requests/s) with a median near 50 to 60 ms.

## Interpretation

- For a **demonstration with a handful of users**, the API with one worker answers in about 60 ms (median), with the decision, its explanation and the audit record included.
- For **dozens of concurrent users**, run several worker processes and use **PostgreSQL**. On this laptop that gave 81 scores a second at 100 users with p95 under 400 ms. SQLite is fine for one process, but under several writing processes it produced lock errors.
- These are **laptop numbers with the load generator on the same machine**, a database in a local container and synthetic example applicants. They show the shape of the limits (CPU per process, then the database writer), not the capacity of any production deployment. Sign-in rate limits were raised only for this test.

## How to repeat

The steps are in the docstring of `tests/load/locustfile.py`: create the throwaway accounts with `python tests/load/locustfile.py --create-accounts 100 --out <temp file>`, start uvicorn with the raised limits and the same `DATABASE_URL`, then run, for example:

```bash
LOANLENS_LOAD_ACCOUNTS=<temp file> locust -f tests/load/locustfile.py --headless -u 100 -r 100 -t 60s \
    --host http://127.0.0.1:8765 --csv <temp dir>/u100
```

Delete the accounts file afterwards. Locust is a development-only dependency (`requirements-dev.txt`).
