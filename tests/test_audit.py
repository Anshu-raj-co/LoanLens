"""Decision audit trail: append-only triggers, the UI and batch paths, history and filters.

The trigger tests run on SQLite always and on PostgreSQL when ``LOANLENS_TEST_POSTGRES_URL``
points at a disposable database (its tables are dropped); otherwise they are skipped.
"""

from __future__ import annotations

import ast
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app_support import TEST_PASSWORD, new_session, open_page
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from loanlens import audit, auth, batch, services, storage
from loanlens.audit import AuditFilters
from loanlens.db import engine as db_engine
from loanlens.db.engine import DatabaseError, normalise_url, session_scope
from loanlens.db.models import DecisionAudit
from loanlens.decision import INPUT_COLUMNS
from loanlens.examples import EXAMPLES

PG_ENV = "LOANLENS_TEST_POSTGRES_URL"
FIXTURE = Path(__file__).parent / "fixtures" / "batch_1000.csv"
SRC = Path(__file__).resolve().parents[1] / "src" / "loanlens"


def _row(**overrides) -> dict:
    values = {
        "inputs": EXAMPLES[0][1], "status": "Approved", "probability": 0.9, "borderline": False,
        "reason_codes": [], "profile": "personal", "policy_version": "1.0.0",
        "policy_hash": "h" * 64, "model_version": "1.0.0", "channel": "ui", "request_id": "r1",
        "user_ref": None, "actor_role": "applicant",
    }  # fmt: skip
    values.update(overrides)
    return audit.build_row(**values)


def _drop_postgres(url: str) -> None:
    db_engine.reset_caches()
    with db_engine.get_engine(url).begin() as conn:
        for table in (
            "decision_audit", "auth_events", "users", "batch_rows", "batch_summaries",
            "alembic_version",
        ):  # fmt: skip
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        conn.execute(text("DROP FUNCTION IF EXISTS decision_audit_append_only() CASCADE"))
    db_engine.reset_caches()


@pytest.fixture(params=["sqlite", "postgresql"])
def any_db(request, tmp_path):
    if request.param == "sqlite":
        yield db_engine.sqlite_url(tmp_path / "audit.sqlite")
        return
    url = os.environ.get(PG_ENV)
    if not url:
        pytest.skip(f"set {PG_ENV} to run the PostgreSQL tests")
    url = normalise_url(url)
    _drop_postgres(url)
    yield url
    _drop_postgres(url)


# ---- Append-only -----------------------------------------------------------------------------


def test_triggers_reject_update_and_delete(any_db) -> None:
    audit.write(any_db, [_row(), _row(status="Rejected")])
    engine = db_engine.get_engine(any_db)
    for statement in (
        "UPDATE decision_audit SET status = 'Approved'",
        "UPDATE decision_audit SET user_ref = NULL",
        "DELETE FROM decision_audit",
    ):
        with pytest.raises(DBAPIError) as exc, engine.begin() as conn:
            conn.execute(text(statement))
        assert "append-only" in str(exc.value)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM decision_audit")).scalar() == 2
        statuses = {r[0] for r in conn.execute(text("SELECT status FROM decision_audit"))}
    assert statuses == {"Approved", "Rejected"}  # unchanged


def test_orm_changes_are_rejected_too(any_db) -> None:
    audit.write(any_db, [_row()])
    with pytest.raises(DatabaseError), session_scope(any_db) as session:
        record = session.execute(select(DecisionAudit)).scalar_one()
        record.status = "Rejected"
    with pytest.raises(DatabaseError), session_scope(any_db) as session:
        session.delete(session.execute(select(DecisionAudit)).scalar_one())
    assert audit.query(any_db)[1] == 1


def test_truncate_rejected_on_postgres(any_db) -> None:
    if db_engine.is_sqlite(any_db):
        pytest.skip("SQLite has no TRUNCATE")
    audit.write(any_db, [_row()])
    with pytest.raises(DBAPIError), db_engine.get_engine(any_db).begin() as conn:
        conn.execute(text("TRUNCATE decision_audit"))


def test_inserts_still_work_in_chunks(any_db) -> None:
    rows = [_row(request_id=f"r{i}") for i in range(25)]
    assert audit.write(any_db, rows, chunk_size=10) == 25
    assert audit.query(any_db, limit=100)[1] == 25


def test_no_update_or_delete_code_paths() -> None:
    """Neither the audit module nor the services contain an UPDATE or DELETE statement."""
    for path in (SRC / "audit.py", SRC / "services.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            for node in ast.walk(tree) if isinstance(node, ast.Call)
        }  # fmt: skip
        assert not names & {"update", "delete", "merge"}, path.name


def test_build_row_keeps_only_model_inputs() -> None:
    row = _row(inputs={**EXAMPLES[0][1], "email": "x@example.com", "name": "X"})
    assert set(row["inputs"]) == set(INPUT_COLUMNS)
    assert isinstance(row["inputs"]["cibil_score"], int)
    with pytest.raises(ValueError, match="channel"):
        _row(channel="email")


# ---- Writes from each path -------------------------------------------------------------------


def test_ui_path_writes_a_record(app_path, artifact) -> None:
    session = new_session()
    at = open_page("pages/1_Check_My_Eligibility.py", session=session).run()
    at.button[0].click().run()
    assert not at.exception
    items = services.my_history(session.principal)
    assert len(items) == 1
    item = items[0]
    assert item["channel"] == "ui" and item["user_ref"] == session.principal.audit_ref
    assert item["actor_role"] == "applicant" and item["profile"] == "personal"
    assert set(item["inputs"]) == set(INPUT_COLUMNS) and item["request_id"]
    assert session.principal.email not in str(item)
    assert any("account history" in c.value for c in at.caption)  # the updated notice


def test_ui_path_without_database_shows_no_result(app_path, artifact, monkeypatch) -> None:
    session = new_session()

    def broken(*_a, **_k):
        raise DatabaseError()

    monkeypatch.setattr(audit, "write", broken)
    at = open_page("pages/1_Check_My_Eligibility.py", session=session).run()
    at.button[0].click().run()
    assert not at.exception
    assert any("could not be saved to your history" in e.value for e in at.error)
    assert not any("Your result" in s.value for s in at.subheader)


class _Upload:
    def getvalue(self) -> bytes:
        return FIXTURE.read_bytes()


def test_batch_path_writes_one_record_per_valid_row(app_path, artifact, monkeypatch) -> None:
    import streamlit as st

    manager = new_session(auth.MANAGER)
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: _Upload())
    at = open_page("pages/2_Bulk_Check.py", session=manager).run()
    assert not at.exception, at.exception
    page = services.audit_records(manager.principal, AuditFilters(channel="batch"))
    assert page.total == 980 and page.counts["total"] == 980
    batch_ids = {r["batch_id"] for r in services.audit_export(manager.principal)}
    assert len(batch_ids) == 1 and None not in batch_ids
    assert all(r["user_ref"] == manager.principal.audit_ref for r in page.items)
    assert storage.latest_summary()["valid_rows"] == 980


def test_batch_records_match_the_results(artifact) -> None:
    manager = new_session(auth.MANAGER).principal
    parsed = batch.parse_upload(FIXTURE.read_bytes())
    run = services.score_batch_upload(manager, parsed, artifact=artifact)
    rows = services.audit_export(manager)
    assert len(rows) == len(run.results)
    by_inputs = {tuple(sorted(r["inputs"].items())): r for r in rows}
    first = run.results.iloc[0]
    values = parsed.values.iloc[0]
    record = by_inputs[tuple(sorted(audit.model_inputs(values).items()))]
    assert record["status"] == first["status"]
    assert record["probability"] == pytest.approx(first["probability"])
    assert record["reason_codes"] == [c for c in first["reason_codes"].split(";") if c]
    assert record["batch_id"] == run.batch_id and record["request_id"] == run.request_id


def test_batch_without_database_shows_no_results(app_path, artifact, monkeypatch) -> None:
    import streamlit as st

    def broken(*_a, **_k):
        raise DatabaseError()

    monkeypatch.setattr(audit, "write", broken)
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: _Upload())
    at = open_page("pages/2_Bulk_Check.py").run()
    assert not at.exception
    assert any("audit trail" in e.value for e in at.error)
    assert not at.get("download_button") or all(
        "results" not in b.label.lower() for b in at.get("download_button")
    )


# ---- History and the manager's view ----------------------------------------------------------


def test_history_is_private(artifact) -> None:
    alice, bob = new_session(), new_session()
    services.score_applicant(alice.principal, EXAMPLES[0][1], artifact=artifact)
    services.score_applicant(alice.principal, EXAMPLES[2][1], product="home", artifact=artifact)
    services.score_applicant(bob.principal, EXAMPLES[4][1], artifact=artifact)
    mine = services.my_history(alice.principal)
    assert len(mine) == 2 and {r["user_ref"] for r in mine} == {alice.principal.audit_ref}
    assert [r["profile"] for r in mine] == ["home", "personal"]  # newest first
    assert len(services.my_history(bob.principal)) == 1


def test_account_deletion_keeps_unlinkable_records(artifact) -> None:
    applicant = new_session()
    services.score_applicant(applicant.principal, EXAMPLES[0][1], artifact=artifact)
    auth.delete_own_account(applicant.principal, TEST_PASSWORD)
    manager = new_session(auth.MANAGER).principal
    rows = services.audit_export(manager)
    assert len(rows) == 1 and rows[0]["user_ref"] == applicant.principal.audit_ref
    assert all(u.email != applicant.principal.email for u in auth.list_users(manager))
    with pytest.raises(auth.InvalidSession):  # nobody can open that history any more
        services.my_history(applicant.principal)


def test_filters_counts_and_pages(artifact) -> None:
    manager = new_session(auth.MANAGER).principal
    applicant = new_session().principal
    for _title, values, _ in EXAMPLES:
        services.score_applicant(applicant, values, artifact=artifact)
    services.score_records(manager, [EXAMPLES[0][1]] * 3, products=["vehicle"] * 3,
                           artifact=artifact)  # fmt: skip
    everything = services.audit_records(manager, page_size=4)
    assert everything.total == 9 and len(everything.items) == 4
    second = services.audit_records(manager, page=3, page_size=4)
    assert len(second.items) == 1
    ids = {r["id"] for p in (1, 2, 3)
           for r in services.audit_records(manager, page=p, page_size=4).items}  # fmt: skip
    assert len(ids) == 9  # pages do not overlap
    assert services.audit_records(manager, AuditFilters(channel="api")).total == 3
    assert services.audit_records(manager, AuditFilters(profile="vehicle")).total == 3
    rejected = services.audit_records(manager, AuditFilters(status="Rejected"))
    assert rejected.total == rejected.counts["rejected"] == everything.counts["rejected"]
    assert all(r["status"] == "Rejected" for r in rejected.items)
    assert services.audit_records(manager, AuditFilters(model_version="9.9.9")).total == 0
    assert services.audit_records(manager, AuditFilters(policy_version="1.0.0")).total == 9
    today = datetime.now(UTC).date()
    assert services.audit_records(manager, AuditFilters(date_from=today, date_to=today)).total == 9
    tomorrow = today + timedelta(days=1)
    assert services.audit_records(manager, AuditFilters(date_from=tomorrow)).total == 0
    yesterday = today - timedelta(days=1)
    assert services.audit_records(manager, AuditFilters(date_to=yesterday)).total == 0
    counts = everything.counts
    assert counts["approved"] + counts["rejected"] == 9 and counts["borderline"] == 2
    options = services.audit_filter_options(manager)
    assert options["profile"] == ["personal", "vehicle"] and options["model_version"] == ["1.0.0"]
    assert services.audit_records(manager, page=0, page_size=10_000).page_size == 500
    with pytest.raises(ValueError, match="start date"):
        AuditFilters(date_from=today, date_to=yesterday)


# ---- Pages -----------------------------------------------------------------------------------


def test_my_history_page(app_path, artifact) -> None:
    session = new_session()
    empty = open_page("pages/7_My_History.py", session=session).run()
    assert any("not made any checks" in i.value for i in empty.info)
    services.score_applicant(session.principal, EXAMPLES[2][1], artifact=artifact)
    other = new_session()
    services.score_applicant(other.principal, EXAMPLES[0][1], artifact=artifact)
    at = open_page("pages/7_My_History.py", session=session).run()
    assert not at.exception
    table = at.dataframe[0].value
    assert list(table.columns)[:6] == ["Date (UTC)", "Loan type", "Status", "Likelihood",
                                       "Borderline", "Reasons"]  # fmt: skip
    assert len(table) == 1 and table["Status"][0] == "Rejected"  # only this user's record
    assert "CIBIL score below the policy minimum" in table["Reasons"][0]
    assert at.get("download_button")


def test_my_history_needs_sign_in(app_path) -> None:
    at = open_page("pages/7_My_History.py", role=None).run()
    assert any("Please sign in" in i.value for i in at.info)


def test_audit_page(app_path, artifact) -> None:
    manager = new_session(auth.MANAGER)
    applicant = new_session()
    services.score_applicant(applicant.principal, EXAMPLES[0][1], artifact=artifact)
    services.score_applicant(applicant.principal, EXAMPLES[2][1], artifact=artifact)
    at = open_page("pages/8_Audit.py", session=manager).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Decisions": "2", "Approved": "1", "Rejected": "1", "Borderline": "0"}
    table = at.dataframe[0].value
    assert {"status", "profile", "channel", "user_ref", "cibil_score"} <= set(table.columns)
    assert "email" not in " ".join(table.columns)
    at.selectbox(key="audit_status").set_value("Rejected").run()
    assert {m.label: m.value for m in at.metric}["Decisions"] == "1"
    at.button(key="audit_prepare").click().run()
    assert at.get("download_button")
    at.selectbox(key="audit_channel").set_value("batch").run()
    assert any("No decisions match" in i.value for i in at.info)


def test_audit_page_is_for_managers(app_path) -> None:
    at = open_page("pages/8_Audit.py", role=auth.APPLICANT).run()
    assert any("bank managers only" in i.value for i in at.info)
    assert not at.dataframe
