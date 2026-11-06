"""Load test of POST /v1/score (dev only; see reports/load_test.md).

Each simulated user signs in once, keeps its token and then scores applications drawn
from the six built-in example applicants (``loanlens.examples``), with a short random pause
between requests. Every score writes an audit record, so measured latency includes it.

1. Create throwaway applicant accounts in a throwaway database through the service layer
   (credentials go to a file outside the repository; delete it afterwards)::

       DATABASE_URL=sqlite:///<tmp>/load.sqlite python tests/load/locustfile.py \
           --create-accounts 100 --out <tmp>/accounts.json

2. Start the API against the same database, with the sign-in limits raised for the load
   test only (the defaults are never changed)::

       LOANLENS_API_AUTH_LIMIT_PER_CLIENT=100000 LOANLENS_API_AUTH_LIMIT_PER_ACCOUNT=100000 \
           uvicorn loanlens.api.app:app --workers 1 --port 8765

3. Run Locust headless::

       LOANLENS_LOAD_ACCOUNTS=<tmp>/accounts.json locust -f tests/load/locustfile.py \
           --headless -u 10 -r 10 -t 60s --host http://127.0.0.1:8765 --csv <tmp>/u10
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import secrets
import sys
import threading
from pathlib import Path

ACCOUNTS_ENV = "LOANLENS_LOAD_ACCOUNTS"


def create_accounts(count: int, out: Path) -> None:
    """Register ``count`` applicant accounts through the service layer; write credentials."""
    from loanlens import auth

    accounts = []
    for i in range(count):
        email = f"load-{i:04d}-{secrets.token_hex(3)}@example.com"
        password = "Load-" + secrets.token_urlsafe(18)
        auth.register_applicant(email, password)
        accounts.append({"email": email, "password": password})
    out.write_text(json.dumps(accounts), encoding="utf-8")
    print(f"Created {count} throwaway accounts.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-accounts", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    create_accounts(args.create_accounts, args.out)
    sys.exit(0)


from locust import HttpUser, between, task  # noqa: E402

from loanlens.examples import EXAMPLES  # noqa: E402

APPLICANTS = [applicant for _title, applicant, _expected in EXAMPLES]
_accounts = json.loads(Path(os.environ[ACCOUNTS_ENV]).read_text(encoding="utf-8"))
_next = itertools.cycle(_accounts)
_lock = threading.Lock()


class Applicant(HttpUser):
    """Signs in once, then scores the example applicants with a 0.5 to 1.5 s pause."""

    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        with _lock:
            account = next(_next)
        response = self.client.post("/v1/auth/login", json=account, name="/v1/auth/login")
        response.raise_for_status()
        self.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    @task
    def score(self) -> None:
        self.client.post("/v1/score", json=random.choice(APPLICANTS), headers=self.headers,
                         name="/v1/score")  # fmt: skip
