"""Phase 9: the benchmark is documented, kept separate, and summarised on the About page."""

from __future__ import annotations

import json
from typing import Any

from loanlens.config import PROJECT_ROOT
from loanlens.presentation import BENCHMARK_SUMMARY

NOTEBOOK = PROJECT_ROOT / "notebooks" / "04_benchmark_bank_loan_data.ipynb"
REPORT = PROJECT_ROOT / "reports" / "benchmark.md"


def _code_cells() -> list[dict[str, Any]]:
    """The notebook's code cells, read as JSON (no notebook package needed)."""
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return [c for c in nb["cells"] if c["cell_type"] == "code"]


def _code() -> str:
    return "\n".join(
        "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        for c in _code_cells()
    )


def test_benchmark_notebook_never_touches_production_model() -> None:
    code = _code()
    for forbidden in ("save_artifact", "train_final", "MODEL_PATH", "loan_approval_dataset"):
        assert forbidden not in code


def test_benchmark_notebook_excludes_sensitive_features() -> None:
    code = _code()
    assert 'drop(columns=["previous_loan_defaults_on_file", "person_gender", "person_age"])' in (
        code
    )
    assert 'assert not {"person_gender", "person_age"} & set(FEATURES)' in code


def test_benchmark_notebook_ran_without_errors() -> None:
    outputs = [o for c in _code_cells() for o in c.get("outputs", [])]
    assert outputs and not any(o["output_type"] == "error" for o in outputs)


def test_benchmark_report_covers_required_points() -> None:
    text = REPORT.read_text(encoding="utf-8")
    for phrase in ("previous defaults", "employment", "home ownership", "USD", "CIBIL", "850"):
        assert phrase.lower() in text.lower(), phrase
    assert "approval decision" in text and "not default" in text


def test_about_page_shows_benchmark(app_path, artifact) -> None:
    from app_support import open_page

    at = open_page("pages/4_About.py").run()
    assert not at.exception
    assert any(s.value == "Benchmark" for s in at.subheader)
    assert any(BENCHMARK_SUMMARY[:60] in m.value for m in at.markdown)
