# Progress

## Phase 0: Setup (done)

**What was done**
- Created the folder structure from CLAUDE.md section 8, using `.gitkeep` files for empty folders.
- Renamed `Data/Raw/` to `data/raw/`. The CSV contents were not touched.
- Created `requirements.txt` (pinned, Python 3.11), `.gitignore` (`.venv`, `__pycache__`, `models/`, `data/raw/`, SQLite files), a minimal `README.md`, and `pyproject.toml` (editable install plus ruff and pytest settings).
- Created `config/policy.yaml`. Every threshold is marked "PLACEHOLDER - illustrative value; a lender would replace it with its own credit policy".
- Created `.venv` (Python 3.11.9), installed the requirements (`pip check` reports no broken requirements), installed the project with `pip install -e .`, and initialised git.

**Test results**
- `ruff check`: all checks passed. `pytest`: no tests yet in this phase.

**Open issues**
- All policy thresholds are placeholders, illustrative until replaced by a lender's real credit policy.
