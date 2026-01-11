# Repository Guidelines

## Project Structure & Module Organization
- `main.py` contains the entry point and application logic.
- `pyproject.toml` defines project metadata and Python dependencies.
- Tests are not yet present; add them under a `tests/` directory when introduced (e.g., `tests/test_scraper.py`).
- Documentation lives in `README.md` (currently empty) and this `AGENTS.md` guide.

## Build, Test, and Development Commands
- `uv run python main.py` runs the current entry point locally.
- `uv venv .venv` then `source .venv/bin/activate` sets up a local virtual environment.
- `uv sync` installs the project dependencies from `pyproject.toml` and `uv.lock`.
- `pip install -r requirements.txt` is not applicable unless a requirements file is added.
- Add dependencies with `uv add <package>` (do not edit `pyproject.toml` manually).

## Coding Style & Naming Conventions
- Use 4-space indentation and standard Python naming: `snake_case` for functions/variables, `PascalCase` for classes.
- Prefer small, focused functions and keep I/O (network, file) separated from parsing logic.
- No formatter or linter is configured yet; if added, document the tool and command here.

## Testing Guidelines
- No testing framework is set up. When tests are added, prefer `pytest` and place files as `tests/test_*.py`.
- Keep tests deterministic; avoid live network calls by using fixtures or cached responses.
- Suggested command once added: `pytest` (from repo root).

## Commit & Pull Request Guidelines
- No Git history exists yet, so no established commit message convention. Use clear, imperative subjects (e.g., "Add news scraper").
- Pull requests should include a short description, testing notes, and any relevant links or screenshots.

## Configuration & Runtime Notes
- The scraper will need network access for `https://www.eet-china.com/news/`.
- If you add configuration (e.g., base URL, page count), prefer environment variables or a small config section in `main.py`.
