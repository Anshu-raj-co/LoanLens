"""Command line: ``python -m loanlens.auth create-manager --email <email>``.

The password is always read with :func:`getpass.getpass` (typed twice, never echoed) and is
never accepted as a command-line argument, so it does not end up in shell history.
"""

from __future__ import annotations

import argparse
import getpass as getpass_mod
import sys
from collections.abc import Callable, Sequence

from loanlens.auth import service
from loanlens.db.engine import DatabaseError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m loanlens.auth", description="Manage LoanLens accounts."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser(
        "create-manager",
        help="Create a bank manager account (the password is asked for, never passed).",
    )
    create.add_argument("--email", required=True, help="Email address of the new manager.")
    return parser


def main(argv: Sequence[str] | None = None, getpass: Callable[[str], str] | None = None) -> int:
    """Run the command; returns the exit code (0 on success)."""
    args = _parser().parse_args(argv)
    getpass = getpass or getpass_mod.getpass
    if args.command == "create-manager":  # pragma: no branch - the only command
        password = getpass("Password for the new manager: ")
        if getpass("Type the password again: ") != password:
            print("The two passwords do not match. No account was created.", file=sys.stderr)
            return 1
        try:
            service.create_manager_account(args.email, password)
        except service.InputError as exc:
            print("No account was created:", file=sys.stderr)
            for problem in exc.problems:
                print(f"- {problem}", file=sys.stderr)
            return 1
        except (service.AccountError, DatabaseError) as exc:
            print(f"No account was created: {exc}", file=sys.stderr)
            return 1
        print("Manager account created. Sign in on the Sign in page.")
    return 0
