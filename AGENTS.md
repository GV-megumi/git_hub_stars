# Agent Instructions

## Project Context

This repository builds a local Github repository health-check web app.

Authoritative documents:

- Requirements: `docs/superpowers/specs/2026-05-26-github-repo-health-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-26-github-repo-health-implementation.md`

## Working Rules

- Use Python 3.11 with a conda environment named `github-health`.
- Keep public repository analysis usable without login.
- Do not add `GITHUB_TOKEN` support. Private repository access must use GitHub App installation tokens.
- Do not write secrets, Github App private keys, model keys, Tavily keys, or installation tokens to git.
- Keep GitHub App permissions read-only. Do not add write operations, create issues, create pull requests, or modify repositories.
- For private repositories, Tavily must remain disabled by default; do not send private repository content to public search or extraction tools.
- If private repository data is sent to an LLM, the UI and API flow must require explicit user confirmation.
- Keep agent tools bounded: fixed endpoints, fixed page limits, summarized outputs, and no arbitrary URL/API execution.

## Development Commands

```powershell
conda create -n github-health python=3.11 -y
conda activate github-health
pip install -r requirements.txt
pytest -v
python run.py
```

## File Conventions

- Backend code lives under `app/`.
- Tests live under `tests/`.
- Static browser files live under `static/`.
- HTML templates live under `templates/`.
- New implementation work should follow the plan task order unless the user explicitly changes scope.

