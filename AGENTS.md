# Bot-Trader Working Rules

This repository is dedicated exclusively to analysis, backtesting, and paper trading.

## 1. Scope and Safety

- The project remains exclusively for analysis, backtest, and paper trading.
- There is no authorization to create or enable a real execution engine.
- Never add private endpoints, real orders, authenticated trading APIs, or balance-moving capabilities without explicit authorization.
- Never weaken kill switches, Telegram authorization, or fail-closed validations.

## 2. Statistical Integrity

- Never fabricate trades, signals, metrics, regimes, provenance, or approvals.
- Synthetic data and fixtures must never become operational evidence.
- Never reduce gates only to force approval.
- Legitimate rejection must be preserved and reported.
- Walk-forward, purge/embargo, costs, and lookahead prevention must remain intact.

## 3. Local Operation

- Do not run `-Prepare`, `-StartSession`, `bot_telegram.py`, or `/vigia` without explicit user authorization.
- Read-only audits never authorize mutations.
- Preserve `paper_data` and all SQLite databases.
- Never delete WAL or SHM files manually.
- Never edit operational databases or JSON files by hand.
- Backup and restore must use only validated administrative flows.

## 4. Secrets and Privacy

- Never print tokens, keys, headers, private messages, IDs, or sensitive payloads.
- Logs and errors must be sanitized.
- Never version `.env`, databases, logs, backups, caches, or operational artifacts.

## 5. Development

- Use the project virtual environment.
- Maintain compatibility with supported Python versions and Windows PowerShell 5.1.
- Use strict parsing and fail-closed behavior.
- Preserve Linux CI compatibility.
- Do not perform refactors outside the task scope.
- Preserve unrelated existing changes.

## 6. Validation

- Run focused tests for the files you change.
- Run the full suite before publishing.
- Run `python -m py_compile` when applicable.
- Run `git diff --check`.
- Report exact tests, warnings, and limitations.
- Do not claim CI passed without real confirmation.

## 7. Git and GitHub

- Never use force push.
- Never rewrite history.
- Work on a specific branch.
- Create normal commits and draft PRs.
- Do not mark a PR ready, merge, or create a tag without explicit authorization.
- Confirm local and remote hashes and a clean working tree.

## 8. Paper Campaign

- Decisions, references, cohorts, campaigns, bindings, and sessions must remain hash-anchored and write-once when the contract requires it.
- Retried operations must be idempotent.
- Missing, divergent, or tampered states must block.
- No paper approval authorizes real operation.

## 9. Change Discipline

- Keep changes minimal and limited to the requested task.
- Preserve existing behavior unless the task explicitly requires a change.
- Prefer corrective, auditable changes over broad rewrites.
