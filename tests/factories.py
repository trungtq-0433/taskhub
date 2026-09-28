"""Object builders shared across the suite.

`make_user` replaces every hand-rolled `User(...)` in the tests: the column is
`NOT NULL` with no default, so a bare `User(username="x")` no longer
constructs. Every user in the suite needs *a* hash, never needs it to verify
against anything, and the suite builds a lot of them — so `TEST_PASSWORD_HASH`
is computed once, here, at import time, rather than once per test. `rounds=4`
is bcrypt's minimum cost factor: real enough to exercise the same code path as
the library default, cheap enough that hundreds of fixtures do not add up to a
slow suite. `verify_password` reads the cost out of the hash itself, so a
value hashed at rounds=4 verifies exactly like one hashed at the production
default of 12 — nothing downstream can tell the difference.
"""

import bcrypt

from app.models import User

TEST_PASSWORD = "correct-horse-battery"
TEST_PASSWORD_HASH = bcrypt.hashpw(TEST_PASSWORD.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode(
    "utf-8"
)


def make_user(username: str, **fields: object) -> User:
    """Build a `User` with a valid hash, unsaved — the caller still adds it."""
    return User(username=username, hashed_password=TEST_PASSWORD_HASH, **fields)
