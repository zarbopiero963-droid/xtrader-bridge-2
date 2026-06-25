# AGENTS.md

## GLOBAL EXECUTION POLICY

This repository uses strict, safe, manual-merge development.

Project goal: maintain and improve **XTrader Signal Bridge**, a Windows desktop bridge that:

1. reads selected Telegram signal chats/channels;
2. parses supported signal formats;
3. writes an XTrader-compatible CSV file;
4. keeps only the intended active signal in the CSV;
5. clears the CSV after a configurable timeout;
6. stores user settings safely;
7. never creates duplicate or stale betting instructions.

The repository is small, but runtime behavior is safety-critical because a wrong CSV row can cause XTrader to place the wrong bet or repeat an old signal.

---

## Core rules

- Only one active task is allowed at a time.
- Only one open pull request is allowed at a time.
- Never work directly on `main`.
- Never merge a PR.
- Never enable auto-merge.
- Merge is always manual and must be done only by the repository owner.
- Never create a second PR while another unrelated PR is open.
- Never execute multiple tasks in parallel.
- Never expand scope beyond the current task, current PR, or provided handoff.
- Never mark work complete while checks are pending, checks are failing, or blocking review comments remain unresolved.
- Every task that modifies code MUST automatically add or update truthful hard tests that exercise the real behavior of the change — including, where relevant, resilience scenarios (crash/power-loss, reconnect, concurrency/race, START/STOP teardown, CSV/dedupe/daily recovery, write-failure with rollback): a code change without matching hard tests is an incomplete PR and cannot be declared `DONE`.
- Never commit secrets, real Telegram tokens, real chat IDs, `.env`, local `config.json`, generated CSV files, build artifacts, logs, caches, EXE files, or ZIP artifacts unless explicitly requested.
- Never add direct betting, browser automation, mouse/keyboard automation, Betfair login, XTrader login automation, or real-money execution beyond CSV output unless explicitly requested by the owner and protected by a dedicated safety plan.

---

## Project-specific safety invariants

The following behavior must be preserved unless the task explicitly asks to change it.

### CSV safety

- The bridge writes XTrader-compatible CSV rows only.
- The CSV must never contain stale signals after the configured clear timeout.
- The CSV must not accidentally append duplicate active signals.
- If the design is “one signal at a time”, preserve it.
- If multi-signal support is requested, add explicit deduplication, timestamping, locking, and tests.
- CSV writes must be atomic or protected enough to avoid partial/corrupt rows.
- CSV header changes are breaking changes and require explicit task approval.
- Do not silently remove existing columns without explaining compatibility impact.
- Do not hardcode a user-specific CSV path such as `C:\Users\...` or `C:\Program Files (x86)\...`.
- Always preserve Windows path compatibility.

### Telegram safety

- Telegram bot token must never be printed in full, committed, or exposed in logs.
- Chat filtering must remain strict.
- If `chat_id` filtering exists, do not weaken it.
- If multi-chat support is added, the user must be able to select enabled chats clearly.
- Do not make the bridge listen to every chat/channel unless the task explicitly requests it and the UI makes it clear.
- Do not process old Telegram messages on startup unless the task explicitly requires replay behavior and deduplication exists.
- Do not retry the same message into the CSV without a deduplication rule.

### XTrader betting safety

- This bridge must only prepare external signal data for XTrader unless explicitly instructed otherwise.
- Do not add direct click automation, direct bookmaker API calls, Betfair API calls, or XTrader GUI control.
- Do not change stake, market, selection, price, min/max price, or bet type behavior silently.
- If a task touches MarketId/SelectionId mode, name-matching mode, stake, price validation, or provider fields, treat it as safety-critical.
- If the task requests both ID-based and name-based CSV modes, keep them selectable and backward compatible.
- Invalid or incomplete parsed signals should be skipped, blocked, or clearly logged; never write a dangerous partial betting row.

### Config persistence safety

- Settings should survive app close/reopen.
- If the task asks for uninstall/reinstall persistence, use a proper user-data folder such as `%APPDATA%` or `%LOCALAPPDATA%`, not the install directory.
- Never store real secrets in committed files.
- If token storage is changed, explain whether it is plain JSON, obfuscated, encrypted, or OS-keychain protected.
- Keep backward compatibility with existing `config.json` where practical.
- Never break START / STOP / close-window cleanup while changing settings.

### GUI safety

- The app must remain usable on Windows.
- Do not remove START, STOP, CSV path, timeout, provider, or log visibility unless explicitly requested.
- New tabs/settings must not hide dangerous options without explanation.
- If adding chat selection, CSV mode selection, or MarketId/SelectionId options, make defaults safe and backward compatible.

---

## Mandatory execution sequence

For any task that modifies code, tests, workflows, parser behavior, CSV behavior, Telegram behavior, config persistence, GUI behavior, or build behavior, the agent must follow this exact sequence:

1. Clean branch preflight.
2. Phase 0 read-only inspection.
3. Patch plan.
4. Narrow patch.
5. Post-fix micro-audit.
6. Hard truthful local validation/tests.
7. Commit and push.
8. Wait until all GitHub checks finish.
9. Collect checks, annotations, review bodies, PR comments, inline comments, and unresolved threads.
10. Review triage.
11. If more patching is needed, repeat from Phase 0.
12. Final hard verify.
13. Report final status.

The agent must not skip Phase 0, post-fix micro-audit, hard truthful tests, check completion gate, review triage, or final hard verify.

If any required step cannot be completed safely, stop and report `NEEDS_MANUAL`, `CHECKS_PENDING`, or `BLOCKED`.

---

## Auto mode detection

Before starting work, determine the mode.

### Mode A — Current PR repair mode

Use this mode if any of these are true:

- The prompt mentions an existing PR number.
- The prompt mentions an existing PR branch.
- The current branch is already associated with an open PR.
- A handoff `.md` references an existing PR.
- The request is about failing checks, review comments, GitHub Actions, Codacy, DeepSource, CodeRabbit, Sourcery, Gitar, or other feedback on an existing PR.
- The request says to continue on the same PR, same branch, or current PR.

Behavior:

- Continue on the existing PR branch.
- Do not create a new branch.
- Do not create a new PR.
- Do not merge.
- Do not work on `main`.
- Fix only the reported current-PR issues.
- Commit and push to the same PR branch.
- Report the commit SHA and new PR head SHA.

### Mode B — New task / new PR mode

Use this mode only if all are true:

- No unrelated open PR exists.
- The request is a new task, not a fix for an existing PR.
- The task is explicitly provided by the repository owner, Codex Web, Codex CLI, Claude, Telegram, GitHub issue/comment, or another clear prompt/handoff.
- The work can be completed without violating scope and safety rules.

Behavior:

- Create a new branch from the correct base branch.
- Implement only the requested task.
- Create exactly one PR.
- Do not merge.
- Include a clear PR body with summary, reason, safety, tests, scope, and notes.

### Mode C — Blocked mode

Use this mode if:

- A different unrelated PR is already open and the request is trying to start a new task.
- The task requires unsafe changes outside allowed scope.
- The requested work would require opening a second PR.
- The requested work would require working directly on `main`.
- The requested work would require merging without explicit owner instruction.
- The current PR branch cannot be determined safely.
- Git remote or credentials are missing and pushing/creating a PR is required.
- The task requires exposing secrets or credentials.
- The task requires real XTrader/Telegram credentials that are not available safely.
- The task would increase betting risk without explicit approval.

Behavior:

- Stop immediately.
- Report `BLOCKED` or `NEEDS_MANUAL_UPDATE_BRANCH`.
- Explain exactly what owner action is required.

---

## Before editing

Always inspect first:

```bash
git status --short
git branch --show-current
git remote -v
find . -maxdepth 3 -type f | sort
```

Then identify:

- current branch;
- current task;
- whether this is a new task or current PR repair;
- files likely needed;
- files that must not be touched;
- safety-critical areas affected.

If the current branch is `main`, create or switch to a proper task branch before editing.

---

## Phase 0 read-only inspection

Before making any code change, the agent must perform a read-only Phase 0.

Phase 0 must identify:

- requested task;
- detected mode: new task or current PR repair;
- current branch;
- whether the branch is `main`;
- open PR state, if any;
- files inspected;
- files likely to be changed;
- files that must not be changed;
- parser/CSV/Telegram/config/GUI/build behavior affected;
- safety risks;
- hard truthful test plan;
- stop conditions.

Phase 0 must not modify files.

Required Phase 0 output:

```text
XTRADER_BRIDGE_PHASE_0

Task:
- <requested task>

Detected mode:
- <New task / Current PR repair / Unknown>

Current branch:
- <branch>

Files inspected:
- <files>

Expected files to change:
- <files>

Forbidden files / artifacts:
- <files or patterns>

Safety risks:
- <CSV stale / duplicate signal / wrong market / token leak / config loss / chat filter weakened>

Patch plan:
- <smallest safe patch>

Hard truthful tests/checks:
- <commands>

Stop conditions:
- <conditions>
```

If Phase 0 cannot determine safe scope, the agent must stop with:

```text
NEEDS_MANUAL

Reason:
- Phase 0 could not determine safe scope.
```

---

## Implementation rules

- Make the smallest safe patch.
- Do not broad-refactor the whole app unless explicitly requested.
- Do not change business behavior silently.
- Keep backward compatibility when possible.
- Prefer adding narrow helper functions over rewriting the entire GUI.
- Keep user-facing text clear and practical.
- Keep Windows compatibility.
- Avoid adding heavy dependencies unless explicitly needed.
- Do not add external services unless explicitly requested.
- Do not add hidden network calls.
- Do not hide errors silently when they affect CSV, Telegram, or config safety.
- Use clear logging, but redact secrets.
- Avoid bare `except Exception: pass` in new code where the error affects safety.
- If changing parser behavior, include examples of accepted/rejected messages.
- If changing CSV behavior, include expected CSV header and example row in tests or docs.

---

## Documentation maintenance — required

Whenever you **add, change, or remove** code (function, class, module, behavior, config
key, CSV column, parser rule, value-map, recognition mode, gate, GUI), you **must update
the corresponding documentation in the same PR**. Docs must never drift from code: a new
function with no doc, or a removed one whose doc still lingers, is an incomplete PR.

In the same PR:

- behavior/usage → update `README.md` and the domain docs (`docs/custom_parser.md`,
  `docs/xtrader_csv_contract.md`);
- new/removed **function, class, or module** → update the function reference docs when
  they exist (see below); until then, describe it in the relevant domain doc and keep the
  **docstring** at the top of the function/module;
- new/removed **config key, CSV column, recognition mode, gate** → update the related docs
  and flag breaking changes in the PR body;
- architecture/audit decisions → `docs/audit/roadmap.md` when relevant.

The post-fix micro-audit and final hard verify must include a **"docs updated for the
change: PASS/FAIL"** check. If you touched code and touched no docs, confirm whether a doc
needs updating; if it genuinely does not (e.g. an internal fix with no impact on documented
behavior/API), state that as a note.

**Future goal (not active yet).** An **auto-generated** function reference (modules →
classes → functions + signature + docstring) in **Markdown + JSONL**, used as the knowledge
base for an in-bridge **AI assistant** (OpenAI vector store + screenshots). Once the
generator (`tools/gen_api_docs.py` or equivalent) and its **CI gate** exist, regenerating
the docs becomes a **mandatory part** of every PR that touches code (the CI gate fails if
they are out of date). Until then, the manual rule above applies.

---

## Post-fix micro-audit

After patching and before running tests, committing, pushing, resolving comments, or declaring completion, the agent must perform a post-fix micro-audit.

The micro-audit must verify:

- only intended files were changed;
- no forbidden files were changed;
- no real Telegram token was added;
- no real chat ID was added;
- no `.env` file was added;
- no local `config.json` with real data was added;
- no generated CSV output was added;
- no logs, caches, EXE, ZIP, build artifacts, or local temporary files were added;
- no auto-merge was enabled;
- no direct betting, Betfair API, XTrader GUI automation, browser automation, or mouse/keyboard automation was introduced;
- no broad unrelated refactor was introduced;
- parser behavior was not changed outside task scope;
- CSV header/columns were not changed unless explicitly required;
- one-signal-at-a-time behavior was preserved unless explicitly changed;
- clear timeout behavior was preserved unless explicitly changed;
- Telegram chat filtering was not weakened;
- config persistence was not broken;
- Windows compatibility was preserved;
- tests or manual verification were updated for changed behavior;
- documentation was updated for the change (README / domain docs / docstring), or a note explains why none was needed.

Required micro-audit output:

```text
POST_FIX_MICRO_AUDIT

Scope:
- PASS / FAIL

Forbidden files:
- PASS / FAIL

Secrets:
- PASS / FAIL

CSV safety:
- PASS / FAIL

Telegram safety:
- PASS / FAIL

Config safety:
- PASS / FAIL

GUI/build safety:
- PASS / FAIL

Duplicate-signal risk:
- PASS / FAIL

Auto-merge/manual merge:
- PASS / FAIL

Result:
- PASS / FAIL

Notes:
- <evidence>
```

If the micro-audit fails:

```text
POST_FIX_AUDIT=FAIL

Reason:
- <why>

Action:
- Do not test.
- Do not commit.
- Do not push.
- Do not resolve review threads.
- Do not declare DONE.
```

The agent may only continue to tests/commit/push if:

```text
POST_FIX_AUDIT=PASS
```

---

## Hard truthful tests

Tests must be real, targeted, and verifiable.

The agent must never claim a test passed unless it actually executed the command and observed a passing exit code.

Forbidden test behavior:

- Do not invent test results.
- Do not write tests that only assert `True`.
- Do not write tests that do not exercise real project functions.
- Do not mark tests as passed because they are “expected to pass”.
- Do not hide failing tests with `|| true`.
- Do not skip tests without a written reason.
- Do not use fake coverage as proof.
- Do not claim GUI, Telegram live, or Windows EXE behavior was tested unless it was actually tested.

Minimum local validation for Python changes:

```bash
python -m py_compile main.py
```

If tests exist:

```bash
python -m pytest -q
```

If parser or CSV behavior changes, add or update hard targeted tests where practical.

Hard parser/CSV tests should exercise real functions, for example:

- `parse_message()` with a valid P.Bet. message;
- `parse_message()` with unsupported/empty input;
- quota conversion from comma to dot;
- `build_csv_row()` with real parsed data;
- `init_csv()` leaves only the header;
- `write_csv()` writes header plus exactly one signal row;
- repeated writes do not append stale rows;
- invalid or incomplete signals do not create dangerous betting rows if validation is added;
- CSV header order remains compatible with XTrader.

Recommended test style:

- Use `tempfile` or pytest `tmp_path` for CSV files.
- Do not use real Telegram tokens.
- Do not call live Telegram APIs in normal unit tests.
- Do not require XTrader to be installed for unit tests.
- Keep unit tests deterministic and offline.
- If a live/manual test is needed, document it separately as manual verification.

### Mandatory hard safety tests for critical runtime behavior

For every change that touches runtime execution, START/STOP, Telegram listener,
reconnect/backoff, auto-start, CSV writing/clearing, signal queue, dedupe,
daily limits, confirmation handling, config persistence, parser routing, GUI
state, or Windows build behavior, the agent must automatically add or update
serious targeted tests before declaring the task complete.

The tests must exercise the real project functions/classes and must cover the
highest-risk failure modes that are practical to test offline:

- power-loss / crash recovery: stale CSV row left on disk must be cleared on
  next app start before any listener auto-start can write again;
- connection loss: reconnect/backoff policy, STOP during backoff, no retry on
  permanent errors, and stale Telegram messages older than `max_signal_age`
  must not write CSV rows;
- auto-start: default off, malformed values fail-closed, token/chat required,
  real mode requires explicit confirmation, and manual START/STOP/close must
  cancel pending auto-start;
- CSV file safety: atomic write, no partial file, no uncontrolled append,
  repeated writes do not duplicate stale signals, clear leaves only the header,
  file-lock/permission failures do not corrupt the previous CSV;
- signal lifecycle: dedupe survives restart, rate limits hold, queue timeouts
  remove expired signals, write failures roll back queue/dedupe/daily state so
  a signal can be retried safely;
- confirmation handling: confirmed/rejected signals are removed from the active
  queue/CSV, unmatched or unclear notifications do not remove anything, and CSV
  write failure after confirmation schedules a safe retry without rewriting
  after STOP;
- config persistence: existing config survives failed saves, corrupted config
  is backed up, defaults remain safe, no real token/chat ID/path is committed,
  and `%APPDATA%`/user-data persistence remains compatible;
- runtime race conditions: START failure must not leave the UI/session active,
  STOP must clear the active session CSV path rather than a changed GUI field,
  expiry/manual clear/process must be serialized, and no old Telegram poller may
  survive a new START epoch.

If a risk cannot be tested automatically because it requires real Windows,
Telegram, XTrader, GUI, or hardware reboot behavior, the agent must add or
update a deterministic offline unit/integration test for the pure logic and
also document an explicit manual smoke test with exact steps, expected result,
and what remains unverified. The agent must not claim the behavior is covered
unless the automated or manual test was actually run and reported with real
evidence.

Required hard test report:

```text
HARD_TEST_EVIDENCE

Commands run:
- <exact command>: PASS / FAIL

Exit codes:
- <command>: <exit code>

What was actually tested:
- <real behavior>

What was not tested:
- <GUI / Telegram live / Windows EXE / XTrader live, with reason>

Test quality:
- REAL / PARTIAL / MANUAL_ONLY

Notes:
- <evidence>
```

If tests cannot be run:

```text
TESTS_SKIPPED

Reason:
- <exact reason>

Risk:
- <what remains unverified>

Required owner action:
- <manual command or environment needed>
```

A task cannot be `DONE` if the only evidence is unrun, fake, decorative, or assumed tests.

---

## Check completion gate — required before final PR review

The agent must not perform final PR review, evidence resolve, thread resolve, or final READY/DONE judgment while GitHub checks are still running.

Before any final decision, the agent must inspect all current-head checks and statuses, including:

- GitHub Actions check runs;
- commit statuses;
- statusCheckRollup;
- Codacy;
- DeepSource;
- CodeRabbit/Sourcery/Gitar if present;
- build/package workflows;
- test workflows.

The agent must wait until all checks are settled.

Settled means there are no checks/statuses in any of these states:

- `PENDING`
- `QUEUED`
- `IN_PROGRESS`
- `WAITING`
- `REQUESTED`
- `EXPECTED`
- `UNKNOWN`
- null / empty / unknown running state

If any check is still pending or in progress, the agent must stop the final control phase and report:

```text
CHECKS_PENDING

Reason:
- Some PR checks are still running.

Pending checks:
- <check name>
```

When checks are pending:

- do not mark the PR ready;
- do not resolve review threads;
- do not reply that findings are fully covered;
- do not declare final `DONE`;
- do not declare `READY_TO_MERGE`;
- do not merge;
- do not start a second PR;
- do not make random extra patches while waiting.

After a push, the agent must re-read the PR only after checks complete on the new current head SHA.

The final review pass must happen in this order:

1. confirm current PR head SHA;
2. wait for all checks to finish;
3. collect check results and annotations;
4. collect PR conversation comments;
5. collect review bodies;
6. collect inline review comments and unresolved threads;
7. classify findings;
8. patch only real current-head blockers;
9. run hard truthful local validation;
10. push if needed;
11. wait again for all checks to finish;
12. only then decide `DONE`, `PARTIAL`, `NOT DONE`, `CHECKS_PENDING`, or `NEEDS_MANUAL`.

A PR is not ready while checks are pending, even if local tests pass.

---

## PR review, inline comments, and evidence resolve

When working on an existing PR, the agent must inspect all current PR feedback sources before deciding that no work is needed.

Required PR feedback sources:

- PR conversation comments.
- PR review bodies.
- PR inline review comments.
- PR review threads.
- Unresolved review threads.
- Outdated vs non-outdated thread state.
- GitHub Actions checks.
- Check annotations.
- Codacy findings.
- DeepSource findings.
- CodeRabbit / Sourcery / Gitar feedback if present.
- Current PR changed files.
- Current PR head SHA.

The agent must not rely only on visible GitHub check names or local tests.

The final review/comment/inline triage must happen only after all checks have completed for the current PR head, because bots may publish comments, annotations, or review bodies only when their checks finish.

### Review triage rules

For every review comment or inline thread, classify it as one of:

- `PATCH_REQUIRED` — active, non-outdated, valid issue that needs a code/test/docs fix.
- `TEST_REQUIRED` — code may already exist, but coverage is missing or unclear.
- `EVIDENCE_RESOLVE` — already fixed or outdated, but needs evidence.
- `SKIP_OUTDATED` — outdated and not applicable to current head.
- `SKIP_DUPLICATE` — duplicate of another handled finding.
- `NEEDS_MANUAL` — unclear, risky, product decision, or outside safe scope.

The agent must fix only active, non-outdated, non-resolved, current-head issues.

Do not chase stale, duplicate, resolved, or unrelated comments.

### Inline comment handling

For inline review comments:

- Read the exact file and line referenced by the comment.
- Check whether the comment still applies to the current PR head.
- If the line changed, inspect the current equivalent code.
- If the issue still exists, patch the smallest safe fix.
- If the issue is already fixed, provide evidence instead of patching again.
- If the comment is outside the current diff or cannot be mapped safely, report `NEEDS_MANUAL`.

### Evidence before resolving

Before replying that a comment is fixed or already covered, the agent must provide evidence:

- commit SHA;
- file path changed or inspected;
- relevant test command;
- real test result;
- explanation of why the issue is fixed, outdated, duplicate, or covered.

Never resolve or mark a review comment handled only because it “seems fixed”.

### Test coverage requirement

If a review comment reports a real bug, regression, parser issue, CSV issue, config persistence issue, Telegram filtering issue, build issue, or duplicate-signal risk:

- Add or update a targeted test when practical.
- Run the targeted test.
- Run `python -m py_compile main.py` for Python changes.
- If no automated test is practical, document the exact manual smoke test.

A PR is not ready if a real review finding was fixed without either automated coverage or a clear documented reason why only manual verification is possible.

### Replying to review threads

For each comment actually fixed, reply in the related GitHub thread with:

```text
Fatto in commit <SHA>
```

and include short evidence when useful:

```text
Fatto in commit <SHA>

Evidence:
- <test command>: PASS
- <file path>: <what changed>
```

For comments skipped or already covered, reply with:

```text
Skipped / already covered

Reason:
- <outdated / duplicate / already fixed / outside scope>

Evidence:
- <test command or file inspection>
```

### Resolving threads

The agent may mark a GitHub review thread as resolved only if all are true:

- all checks are completed for the current PR head;
- the thread is active and non-outdated;
- the related issue is fixed or demonstrably already covered;
- relevant tests/checks pass;
- current PR head SHA matches the commit being reported;
- the repository owner or automation mode explicitly allows resolving threads.

If resolve permission is unavailable, reply with evidence but do not claim the thread was resolved.

Never resolve a thread when:

- checks are still pending;
- tests are failing;
- evidence is missing;
- the fix is only assumed;
- the comment is unclear;
- the fix would require unsafe scope expansion;
- the thread requires owner/product decision.

---

## Final hard verify

Before declaring `DONE`, `READY`, or `PARTIAL`, the agent must perform a final hard verify.

Final hard verify requires:

- Phase 0 completed;
- post-fix micro-audit passed;
- hard truthful local validation completed;
- all current-head GitHub checks completed;
- failing checks triaged;
- review bodies read;
- PR comments read;
- inline review comments read;
- unresolved review threads read;
- real findings patched or marked with evidence;
- no blocking review comments remain unevidenced;
- no pending checks remain;
- no auto-merge;
- merge remains manual.

Required final hard verify output:

```text
FINAL_HARD_VERIFY

Phase 0:
- PASS / FAIL

Post-fix micro-audit:
- PASS / FAIL

Hard truthful tests:
- PASS / FAIL / SKIPPED with reason

Hard tests created/updated for the change:
- PASS / FAIL / N/A with reason

GitHub checks completed:
- YES / NO

GitHub checks result:
- PASS / FAIL / PENDING

PR comments checked:
- YES / NO

Review bodies checked:
- YES / NO

Inline comments checked:
- YES / NO

Unresolved threads checked:
- YES / NO

Safety invariants:
- PASS / FAIL

Merge:
- MANUAL ONLY

Final status:
- DONE / PARTIAL / NOT DONE / CHECKS_PENDING / NEEDS_MANUAL
```

If any required final hard verify item is missing, do not declare `DONE`.

---

## Handoff file behavior

A handoff file may contain failing checks, logs, annotations, review comments, and a section such as:

```text
FIX THESE ISSUES ONLY
```

When a handoff file is provided for the current PR:

- Treat it as the source of truth for the current PR fix cycle.
- Start from `FIX THESE ISSUES ONLY` if that section exists.
- Fix only the deduplicated issues listed there.
- Use failing checks, logs, annotations, and review comments as evidence.
- Ignore duplicated old monitor comments.
- Ignore Node.js/action deprecation warnings unless they directly block the current PR.
- Do not chase unrelated style cleanup outside files touched by the PR.
- Do not refactor unrelated code.
- Do not modify unrelated tests.
- Do not change bridge behavior unless the handoff/task explicitly requires it.

If the handoff conflicts with repository rules, follow repository rules and report the conflict.

If the handoff asks to create a new PR while the current task already has an open PR, do not create a new PR. Continue on the existing PR branch and report that the handoff was interpreted as a current-PR fix request.

---

## Git and branch safety

Before making changes:

- Confirm the current branch is not `main`.
- If fixing an existing PR, confirm the branch matches the current PR branch.
- If creating a new PR, create a dedicated task branch from the correct base.
- Confirm the Git remote exists.
- Fetch the latest remote state before editing.
- Do not force-push unless explicitly instructed by the repository owner.

When committing:

- Commit only relevant files.
- Use a clear commit message.
- Do not include generated temporary files, logs, secrets, local caches, CSV output, local config, EXE files, or ZIP artifacts.
- Push only to:
  - the existing PR branch in current-PR repair mode; or
  - the newly created task branch in new-task mode.

If unable to push, respond exactly:

```text
NEEDS_MANUAL_UPDATE_BRANCH
```

Then explain why, including:

- current branch;
- expected branch;
- whether `git remote -v` exists;
- whether push failed;
- whether credentials are missing.

---

## Scope control

- Modify only files required by the task, checks, review comments, or handoff.
- Do not refactor unrelated code.
- Do not expand scope.
- Do not change parser/CSV/betting behavior unless explicitly required.
- Do not modify CI configuration unless the task or failing check specifically requires it.
- Do not silence tests or checks just to make the PR green.
- Do not delete tests unless explicitly required and documented.
- Do not remove safety guards.
- Do not bypass static/security findings by ignoring them without justification.
- Do not add real secrets or sample secrets.

---

## Stop conditions

Stop immediately and report `BLOCKED` if:

- A different unrelated PR is already open and the current request is trying to start a new task.
- The task requires unsafe files outside allowed scope.
- The task would require direct work on `main`.
- The task would require auto-merge.
- The task would require exposing Telegram tokens, chat IDs, credentials, or local secrets.
- The task would require disabling safety behavior without explicit owner approval.
- The task would increase duplicate-bet risk without a clear deduplication plan.
- The task would write malformed or partial CSV rows.
- The task would process Telegram messages from unapproved chats.
- The requested mode cannot be determined safely.

Do not stop if:

- The task is to fix the currently open PR.
- The task is triggered by GitHub review comments on the currently open PR.
- The task is triggered by failing checks on the currently open PR.
- The task is triggered by Codacy/DeepSource/CodeRabbit/Sourcery/Gitar feedback on the currently open PR.
- The task is triggered by a handoff `.md` file for the currently open PR.

In those cases:

- Continue on the same PR.
- Push to the same PR branch.
- Do not open a new PR.
- Do not merge.
- Report what changed and provide the commit SHA.

---

## Completion definition

A task is not complete until:

- The PR has been created or updated.
- Phase 0 has passed.
- Post-fix micro-audit has passed.
- Hard truthful local tests have passed or are explicitly skipped with a real reason.
- All current-head checks have completed.
- Relevant checks have passed or are clearly outside scope.
- CSV/Telegram/config safety impact is explained.
- Blocking review comments are resolved, outdated, or explicitly handled with evidence.
- The PR is ready for owner review.

Do not mark work complete while checks are failing.
Do not mark work complete while checks are pending.
Do not mark work complete while active review comments remain unresolved.
Do not mark work complete after only editing files without running at least `py_compile` for Python changes.
Do not mark work complete with fake, assumed, or decorative tests.

---

## Required response format after creating a new PR

```text
DONE / PARTIAL / NOT DONE / CHECKS_PENDING / NEEDS_MANUAL

Summary:
- <what was changed>

Branch:
- <branch name>

PR:
- <PR URL or number>

Commit:
- <commit SHA>

Safety:
- <CSV / Telegram / config / duplicate-bet impact>

Phase 0:
- PASS / FAIL

Post-fix micro-audit:
- PASS / FAIL

Hard truthful tests:
- <command run>: pass/fail/skipped with reason

GitHub checks:
- complete/pass/fail/pending with reason

Review comments handled:
- <thread/comment URL or summary>: fixed/skipped/needs manual with evidence

Files changed:
- <file path>

Files created:
- <file path>

Final hard verify:
- DONE / PARTIAL / NOT DONE / CHECKS_PENDING / NEEDS_MANUAL

Notes:
- <anything the repository owner must know>
```

If unable to create the PR or push the branch, respond exactly:

```text
NEEDS_MANUAL_UPDATE_BRANCH
```

and explain why.

---

## Required response format after fixing current PR

```text
DONE / PARTIAL / NOT DONE / CHECKS_PENDING / NEEDS_MANUAL

Summary:
- <what was changed>

Commit:
- <commit SHA>

New PR head SHA:
- <new PR head SHA>

Safety:
- <CSV / Telegram / config / duplicate-bet impact>

Phase 0:
- PASS / FAIL

Post-fix micro-audit:
- PASS / FAIL

Hard truthful tests:
- <command run>: pass/fail/skipped with reason

GitHub checks:
- complete/pass/fail/pending with reason

Review comments handled:
- <comment/thread URL or summary>: fixed in commit <SHA>; evidence: <test command PASS>
- <comment/thread URL or summary>: skipped because <reason>; evidence: <file/test>
- <comment/thread URL or summary>: needs manual because <reason>

Files changed:
- <file path>

Final hard verify:
- DONE / PARTIAL / NOT DONE / CHECKS_PENDING / NEEDS_MANUAL

Notes:
- <anything the repository owner must know>
```

If unable to push to the PR branch, respond exactly:

```text
NEEDS_MANUAL_UPDATE_BRANCH
```

and explain why.

---

## Required response format when blocked

```text
BLOCKED

Reason:
- <why work cannot proceed safely>

Detected mode:
- <Current PR repair / New task / Unknown>

Current state:
- Open PR: <number or unknown>
- Current branch: <branch or unknown>
- Expected branch: <branch or unknown>

Required owner action:
- <what the repository owner must do next>
```

---

## Required response format when checks are pending

```text
CHECKS_PENDING

Reason:
- Current-head PR checks are not all finished yet.

Current head:
- <SHA>

Pending checks:
- <check name>

Next allowed action:
- Wait for checks to complete, then re-read checks, annotations, review bodies, inline comments, unresolved threads, and only then decide final status.
```

---

## Automation-specific rules

Automated agents, Codex CLI, Claude, self-hosted runners, Telegram, GitHub Actions, and handoff bots must follow this file.

For new-task automation:

- Run only when no unrelated PR is open.
- Create one branch.
- Create one PR.
- Do not merge.
- Stop after PR creation and notify the owner.

For automated PR repair loops:

- Use the handoff file as input.
- Apply only current PR fixes.
- Make at most one fix commit per automation attempt.
- Push only to the current PR branch.
- Let GitHub checks run after push.
- Wait until checks complete before final review/comment/inline triage.
- If checks remain red, generate or wait for a new handoff and run another controlled attempt.
- Do not loop forever.
- Stop after the configured maximum attempts and notify the owner.

Recommended automation limit:

```text
Maximum automatic attempts per PR/check state: 3
```

If the maximum attempt limit is reached:

```text
PARTIAL

Summary:
- Automatic repair attempts reached the configured limit.

Notes:
- Owner review required before continuing.
```