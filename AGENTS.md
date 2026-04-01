# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/browser_session_hub/`. Use `app.py` for FastAPI wiring, `cli.py` for the service entrypoint, `config.py` for environment parsing, and `session_manager.py` for browser lifecycle logic. API schemas live in `models.py`. Static dashboard assets are bundled from `src/browser_session_hub/static/`. Tests mirror the package structure under `tests/` with focused modules such as `tests/test_app.py` and `tests/test_session_manager.py`.

## Build, Test, and Development Commands
Create an editable environment before changing code:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Run the service locally with `browser-session-hub` or `python -m browser_session_hub`. The default dashboard is `http://127.0.0.1:8091`.

Run tests with:

```bash
pytest
```

Use `pytest tests/test_app.py -q` when iterating on one area. This project relies on host binaries such as Chrome/Chromium, `Xvfb`, `x11vnc`, and `novnc_proxy`; check `README.md` before testing full runtime flows.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, type hints on public functions, `from __future__ import annotations`, and concise module docstrings. Keep modules small and responsibility-driven. Use `snake_case` for functions, variables, and test names; use `PascalCase` for dataclasses, Pydantic models, and exceptions. No formatter or linter is configured in `pyproject.toml`, so match the current code style closely and avoid unrelated reformatting.

## Testing Guidelines
Tests use `pytest` with `fastapi.testclient.TestClient` and `tmp_path`/`monkeypatch` fixtures. Name files `test_*.py` and keep each test focused on one behavior. Prefer mocking browser-process startup like the existing session manager tests instead of depending on real system binaries in unit tests.

## Commit & Pull Request Guidelines
This workspace snapshot does not include `.git`, so local commit history is unavailable. Until history is restored, use short imperative commit subjects such as `Add idle session cleanup test` and keep each commit scoped to one change. PRs should describe behavior changes, list test coverage, note any required environment variables or Linux packages, and include screenshots when dashboard UI files under `static/` change.

## Security & Configuration Tips
Treat `BROWSER_SESSION_HUB_*` environment variables as the supported configuration surface. Do not hardcode machine-specific binary paths or session roots in source files; keep overrides in the environment.
