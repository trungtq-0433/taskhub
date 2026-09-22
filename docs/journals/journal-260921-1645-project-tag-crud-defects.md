# Document-verified holes: Three defects that hid from the test suite, and two promises we made but never kept

**Date**: 2026-09-21 16:45
**Severity**: high
**Component**: Project and Tag CRUD; database layer; async ORM integration; Alembic migrations
**Status**: resolved

## What Happened

Four planned phases shipped (models+migrations, test harness, DTOs+repositories, services+routers), passed lint/mypy/pytest on the developer's machine with a transactional test suite, passed adversarial review under real conditions, then every issue the review found was concrete and not hypothetical. Seven commits total: four forward, then a fix commit that addressed findings, then two documentation commits. The branch delivered full CRUD for two entities, 53 passing tests (was 20), and the first real migration into a Postgres database — and it surfaced exactly what only a real database, an external reviewer, and deliberate sabotage tests can uncover.

## The Brutal Truth

Three defects hid from every static check — no lint error, no mypy error, no test failure — until the code ran against real hardware. Two safeguards were written down on paper, baked into the acceptance criteria and the plan's risk table, and then simply never built. Both strands sting because they were avoidable: one by reading code that was already there, one by reading the document you wrote. The real work started after "done" looked complete.

## Technical Details

**Defect 1: MissingGreenlet on read of database-computed timestamps**

After a PATCH, reading `updated_at` raised `greenlet.exc.MissingGreenlet`. Both `created_at` and `updated_at` are computed by the database with `server_default` and `onupdate` — the ORM marks them expired after any DML and attempts a lazy refresh to reload them, which is I/O and forbidden in async SQLAlchemy. Fix was `eager_defaults=True` on the entity mixin, which uses `RETURNING` to fetch the values in the same statement. The comment in the mixin (`app/models/mixins.py:7-29`) now carries the full explanation so the next person does not rediscover it: `expire_on_commit=False` does not help because the expire happens at the flush, not at the commit.

Error signature: `greenlet.exc.MissingGreenlet: "no running event loop"` when reading any server-default or onupdate column after an async flush in a test, or after any mutation in a running app.

**Defect 2: Alembic migration unconditionally overwrites the database URL**

`migrations/env.py:34` in the initial commit (`79dc1f9`) had `config.set_main_option("sqlalchemy.url", settings.database_url)` with no guard. The test harness tries to point Alembic at `taskhub_test` and sets `ALEMBIC_SQLALCHEMY_URL` to override it, but `env.py` was overwriting that every time. Had it not been caught during the harness build, running `alembic upgrade head` during test setup would have migrated the developer's own `taskhub` database instead of the test database, silently destroying the schema and data. Fix: only set the URL if no caller has already supplied one (lines 34-38 now). The guard is documented in a four-line comment explaining why unconditional was wrong.

Near-miss: the code would have corrupted the development database silently on the first full test run. Discovered because the test harness itself required the migration to work against a different database, forcing the condition to the surface.

**Defect 3: Ruff reformatting Python inside Markdown fences**

Five `.md` files across `docs/` and `plans/` carry Python in fences, including Mako template syntax that is not valid Python. `ruff format --check .` reported them as needing reformatting — caught before `ruff format .` was run, so nothing was actually mangled, but the next run would have rewritten documentation examples. This is not a defect in the code — it's a configuration issue. The fix was already in `pyproject.toml` but the rule explains why: documentation code samples are written to be read, not to satisfy a formatter, and some are deliberately not valid Python. The `extend-exclude = ["*.md"]` rule is in place now.

Error signature: `ruff format --check` reported five `.md` files needed reformatting; re-running `ruff format` corrupted Mako syntax in migration template examples.

---

**Gap 1: Unreachable database answered 500, not 503 (documented requirement, never built)**

`docs/api-conventions.md` §6 states: *"A constraint for the services that arrive with the entities; nothing catches these yet... a service that needs to tell 'the database is down' apart from 'the query was wrong' catches `(SQLAlchemyError, OSError)`."* The document was written in the same session as the phase-04 plan ("constraint for the services that arrive with the entities"). No service did. Live probe confirmed: with the database unreachable (engine pointed at a closed port) and `DEBUG=false`, `GET /api/v1/projects` returned `500 internal-error`, not `503 service-unavailable`. Clients and load balancers both key retry/circuit-breaker logic on 503; a 500 pages as a bug, not an outage.

Root cause: asyncpg raises the socket error unwrapped (`ConnectionRefusedError`, `socket.gaierror`, `TimeoutError`), so it never reaches the `SQLAlchemyError` handler and falls through to the catch-all. The fix was a central `connection_error_handler` in `app/core/handlers.py:140-157` that catches `OSError` and maps it to 503. The doc now describes what the code does. The reviewer recommended catching it in each service method, but a central handler was chosen instead — six lines repeated across ten service methods is how one of them ends up missing it (see Lessons Learned).

Error string from the failed probe: `500 {"type":"urn:taskhub:problem:internal-error", ...}` when hitting any endpoint with the database offline.

**Gap 2: Test harness cannot detect a missing `commit()` (risk-table claim not kept)**

Phase-04's own risk table: *"Service forgets `commit()` — request succeeds, data vanishes. Caught by: test re-reads through a fresh session after the request."* This was not caught. The `api_client` fixture hands every request in a single test the same `db_session` object, and a flushed-but-uncommitted row is visible to the session that wrote it. The risk table's safeguard was illusory.

Demonstrated: deleted `commit()` from `ProjectService.create`, then ran the test-suite sequence (POST, GET). Result: POST returned 201 with a full body, GET returned 200 with the same row — because `flush()` made it visible on that connection, commit or not. Ran the same sequence through a separate, independent session opened directly against the engine: `None`. In production (one session per request) this bug would drop every write while responses look successful.

The fix was `tests/test_service_commits.py:1-90`, which uses genuinely separate sessions for write and read, commits for real, and cleans up afterward. The same sabotage (deleting `commit()`) fails the test now. Verified by the evidence gate: when the commit is present, the test passes; when it is deleted, the test fails; when it is restored, the test passes again. The test is slower (no transaction rollback) and smaller in scope, but it actually proves durability.

## What We Tried

1. **For MissingGreenlet**: `expire_on_commit=False` was already set on the session factory, from the foundation phase weeks earlier — which is exactly why the failure was confusing. It was never a candidate fix; it was a safeguard already in place that does not cover this case, because the expire happens on flush, not commit. `eager_defaults=True` on the mixin, reloading via RETURNING in the same statement, is what worked.

2. **For the Alembic URL overwrite**: Added an `assert_not_the_dev_database` function and a guard in `get_session` to prevent writes to the wrong database at runtime. This would catch the corruption, but too late — the schema would already be modified. Then added the `only-if-not-set` guard in `env.py` so the harness can point migrations at the test database without having it overwritten.

3. **For Ruff and Markdown**: Added `extend-exclude = ["*.md"]` in `pyproject.toml`. Ruff now respects the boundary between code and documentation.

4. **For the 503 gap**: The reviewer recommended catching `(SQLAlchemyError, OSError)` in each service method. Instead, registered a central exception handler for `OSError` at the app level. This way, the condition is defined once, the behavior is consistent across all endpoints, and a future service method that forgets to catch gets 503 anyway.

5. **For the commit test gap**: Created a new test file (`test_service_commits.py`) that runs write-then-read against genuinely independent sessions. Slower, and the point: proves the write actually left the transaction, not just the flush buffer.

## Root Cause Analysis

The three defects have different shapes but a shared source: **the test suite is fast and isolated precisely because it shares a session and a transaction within each test, and that same design makes it blind to the bugs that surface only when sessions are independent or hardware is real.**

- **MissingGreenlet**: The transaction test harness rolls back after each test, so the code never runs another ORM operation (like reading `updated_at`) on a committed row. A production request that doesn't read the timestamps never hits this. The defect only surfaces when the application reads them back for a response, which the test never does.

- **Alembic URL**: The test harness sets the database URL before importing Alembic, so if `env.py` overwrote it unconditionally, the test would catch the new URL pointing at the test database — but the test harness development itself, not the application tests. No test of Alembic integration exists in the suite.

- **Ruff and Markdown**: Not a defect, a configuration issue. Found because the code-review setup ran the full quality gate, including format checks.

The two gaps are different still — they are **things we documented or promised but never built:**

- **Unreachable-database 503**: The doc was written. The plan's phase-04 says "constraint for the services that arrive with the entities." The code came; the feature did not. Reading the document, the test suite, and the open acceptance criteria in the same order would have caught this. Reading them in the order (code, test, doc) meant the doc looked like a future concern.

- **Cross-session commit test**: The risk table said the regression is "caught by" fresh-session re-read. That was aspirational, not true. The test harness design (one session per test) made it impossible to write a test that actually verifies the claim. The risk table was honest about the vulnerability; the implementation was not.

## Lessons Learned

1. **Paper is cheaper than bugs.** Both gaps were written down — one in a doc, one in a risk table. Reading the doc before writing the code, or reading the risk table after writing the code and actually building what it claimed, would have prevented the merge with an incomplete feature. This is not about plan discipline — it's about letting plans be the northstar, not the decoration.

2. **Defects that hide from transactional tests need real conditions to surface.** A test suite that rolls back every transaction is a gift for isolation and speed. It is also a blind spot. For async ORM behavior, database-independent code paths, and durability guarantees, a handful of slower, durable tests (or a real probe) have to run. The test suite cannot be the only voice.

3. **Code and doc disagreement is not ambiguity — it's a choice to resolve.** `docs/api-conventions.md` said 503 for database down; the code said 500. The honest move is not "both are fine" — it's to decide which is right and align them. Leaving them out of sync is betting that nobody will care. The reviewer and the evidence gate did.

4. **Safeguards should be written once and applied everywhere, not once per place.** The alternative to the central `connection_error_handler` was to add a try/catch in ten service methods. Six lines repeated ten ways means nine of them will be correct and one will be forgotten or will drift. The `OSError` handler lives in the exception-handler pipeline, so every endpoint inherits the behavior without thinking. Smaller surface area for mistakes.

5. **The test harness design that makes tests fast makes them blind.** Sharing a session per test is a clever trick for speed and isolation. It is also a Faraday cage against a whole class of bugs. For durability, transaction boundaries, and session-lifetime concerns, a separate, slower test with independent sessions is not a luxury — it is the only way to prove the property. The risk table's assumption that fresh-session re-reading would catch missing commits was sound; the test harness's ability to run that test was impossible.

6. **Configuration is code.** The Ruff markdown issue was caught because the code-review setup included the full quality gate. A missing `extend-exclude` rule is as much a defect as a logic error — it silently corrupts artifacts. The configuration file matters.

## Next Steps

- Alembic migrations will continue to require a guard in `env.py` for any future test harness that needs to point them at a different database. The comment in `migrations/env.py:34-38` explains the guard so the next person doesn't remove it by accident.
- Any new entity that gets CRUD endpoints must include a cross-session durability test (modeled on `test_service_commits.py`) to prove writes actually persist. The existing test is the template.
- New services that touch the database should be probed manually once with the database offline, to verify they answer 503 and not 500. The `connection_error_handler` catches `OSError`, but logic errors that raise something else will still slip through.
- Phase-04 risk table gets a final audit before any future CRUD lands: every "caught by" claim gets matched to actual test code. If a test is asymmetrical (checking the happy path but not the sabotaged path), the table gets corrected.
- The docs/api-conventions.md contract is now enforced — every service that arrives henceforward must satisfy §6. Mark it as a hard gate in the phase plan's "done when" checklist.

---

**Status:** DONE
**Summary:** Project and Tag CRUD shipped with 53 passing tests and 7 commits. An adversarial review uncovered three defects that hid from static checks and a real database, plus two gaps between promises and implementation. All issues were resolved and gated by evidence before merge.
**Concerns/Blockers:** None — gated by evidence and human sign-off before merge.
