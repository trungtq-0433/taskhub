"""Password hashing and access tokens.

Four functions, nothing more: no database lookup, no HTTP, no request
object. `app.api.auth` composes these with a repository to build
`get_current_user`; keeping them separate is what makes each side testable
without the other.

Hashing runs through `run_in_threadpool` because `bcrypt` is synchronous and,
at the library's default cost factor, deliberately slow (that slowness is the
whole point of bcrypt) — calling it directly from an `async def` would block
the event loop for every other request in flight for the duration of one
hash. `PASSWORD_MAX_BYTES` in `app.constants` is what keeps a client from ever
handing bcrypt more than 72 bytes in the first place; enforcing that is the
password schema's job; this module just reflects a malformed hash back as
"does not verify" rather than raising.
"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

# Not a setting: making the algorithm configurable only invites a `none`/RS256
# downgrade mix-up (decision 7 in the auth plan). HS256 is the one value this
# codebase ever signs or accepts.
JWT_ALGORITHM = "HS256"


async def hash_password(plain: str) -> str:
    """Hash `plain` with bcrypt at the library's default cost factor (12)."""
    encoded = plain.encode("utf-8")
    hashed = await run_in_threadpool(bcrypt.hashpw, encoded, bcrypt.gensalt())
    return hashed.decode("utf-8")


async def verify_password(plain: str, hashed: str) -> bool:
    """Check `plain` against a stored hash.

    `bcrypt.checkpw` raises `ValueError` for a value it cannot parse as a
    bcrypt hash at all — a corrupted row, say. That is treated the same as a
    wrong password: the caller only ever needs to know whether the credential
    was good, not why it was not.
    """
    try:
        matches = await run_in_threadpool(
            bcrypt.checkpw, plain.encode("utf-8"), hashed.encode("utf-8")
        )
    except ValueError:
        return False
    return matches


def create_access_token(user_id: int, *, now: datetime | None = None) -> str:
    """Sign a token whose only claim of substance is the user's id.

    `now` is injectable so tests can mint an already-expired token without
    sleeping for real.
    """
    issued_at = now if now is not None else datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "iat": issued_at, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Recover the user id a token claims, or `None` if it should be refused.

    `algorithms=[JWT_ALGORITHM]` pinned explicitly is what refuses an
    `{"alg": "none"}` token or one signed with any algorithm but this one —
    PyJWT 2 already requires `algorithms` and refuses to decode without it,
    and pinning it to a single value is what keeps a token that names a
    different algorithm from being accepted at all. Every other failure (bad
    signature, expired, missing claim, malformed) is `jwt.InvalidTokenError`
    or a subclass, and every one of them means the same thing to the caller:
    no id. The caller still has to look the id up — a token can outlive the
    user it names.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError:
        return None

    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
