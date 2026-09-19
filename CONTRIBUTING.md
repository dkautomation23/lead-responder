# Contributing

## Setup

```bash
git clone https://github.com/dkautomation23/lead-responder.git
cd lead-responder
pip install -r requirements.txt
cp rules.example.yaml rules.yaml
```

`requirements.txt` pulls in one dependency, PyYAML.

Give this repository its own virtual environment. Do not point it at a venv
shared with another project — a shared environment hides a missing or
mismatched dependency until CI, or a user, hits it first.

`rules.yaml` is listed in `.gitignore` and must stay that way; it is your
local copy for testing. Only `rules.example.yaml` is tracked.

## Running the checks

CI runs exactly this, on Python 3.10 and 3.12:

```bash
python -m compileall -q .
python respond.py --selftest
```

There is no `tests/` directory in this repo. The `selftest()` function inside
`respond.py`, run through `python respond.py --selftest`, is the test suite:
it builds sample payloads in memory and calls `handle()` on them, checking
scoring, routing, the budget and phone parsers, and slot generation.

## Adding a check or fixing a bug

Same test-first idea, applied to where the tests actually live:

1. Add a failing case to the `selftest()` function in `respond.py`, using the
   existing `check(label, condition)` helper. Run
   `python respond.py --selftest` and confirm it fails for the reason you
   expect.
2. Implement the fix.
3. Run `python respond.py --selftest` again and confirm every check passes.

## Commit messages

Keep them short and descriptive. This repo's history so far uses both a
plain sentence and a `type: description` form, copied here verbatim:

```
lead-responder: score, answer and route an inbound lead in under a second, rules in YAML
Run the tests in CI on every push
```

## Pull requests

- Keep the change scoped to one thing.
- CI (byte-compile + `--selftest`, on Python 3.10 and 3.12) must pass.
- Do not commit secrets or credentials.
- Do not commit a real `rules.yaml` with live routing addresses (phone
  numbers, `owner_channel`, etc.) — only `rules.example.yaml` is tracked, and
  `rules.yaml` is gitignored on purpose.
