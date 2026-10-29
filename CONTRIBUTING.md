# Contributing

Thanks for helping. This is a small project, so the rules are short.

## Set up

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"      # add ,cuda for an NVIDIA GPU
.venv\Scripts\python -m pytest -q -m "not slow and not llm"
.venv\Scripts\python -m ruff check .
```

`-m llm` runs the cleanup tests against a real Ollama server and needs the cleanup model installed.
Tests marked `slow` drive the real keyboard and clipboard; run them on a desktop you are not using.

## Rules that matter

1. **Never make correct text wrong.** Anything that changes what the user said (corrections,
   symbols, links, dictionary matching, casing) must leave text alone when unsure. Add tests for
   the sentences that must NOT change, not only for the ones that should.
2. **Privacy.** No network calls except the labelled model download and Ollama on `127.0.0.1`. No
   audio, dictation text, databases, models or personal data in commits, tests or screenshots.
   Write test sentences yourself; do not copy real dictations.
3. **Typed code**, `from __future__ import annotations`, ruff line length 100, a test for each
   module.
4. **Record decisions** in `DECISIONS.md` (one entry with the reason) and user-visible changes in
   `CHANGELOG.md`.

## Versions

Each release bumps the version in `pyproject.toml`, `src/flow/__init__.py` and the top entry of
`CHANGELOG.md` (a test checks they agree) and gets a tag `vX.Y.Z`. A new feature raises the middle
number, a fix the last one. To go back to an older version: `git tag`, then `git checkout vX.Y.Z`.

## Bug reports

Run `python -m flow selftest` and paste its output (it holds no user name or device names). Say what you said and what came out, but do not
paste anything private.
