"""Password hashing and access tokens — the four pure functions auth needs.

No database, no app, no HTTP: everything here is a function of its arguments,
which is the point of keeping them in `app.core.security` rather than inline
in a router.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


async def test_a_hash_verifies_against_the_password_it_was_made_from() -> None:
    hashed = await hash_password("correct-horse-battery")

    assert await verify_password("correct-horse-battery", hashed) is True


async def test_the_wrong_password_does_not_verify() -> None:
    hashed = await hash_password("correct-horse-battery")

    assert await verify_password("wrong-password", hashed) is False


async def test_a_malformed_hash_fails_closed_instead_of_raising() -> None:
    """`bcrypt.checkpw` raises `ValueError` on a hash it cannot parse.

    A stored value that is not a bcrypt hash at all (corruption, a bad
    migration, a fixture typo) must not turn into a 500 — it is exactly the
    same as a password that does not match.
    """
    assert await verify_password("anything", "not-a-bcrypt-hash") is False


async def test_two_hashes_of_the_same_password_differ() -> None:
    """A fresh salt every call — otherwise two users with the same password
    would have identical rows, which leaks who shares a password with whom.
    """
    first = await hash_password("correct-horse-battery")
    second = await hash_password("correct-horse-battery")

    assert first != second


async def test_a_fresh_token_round_trips_to_the_id_it_was_made_for() -> None:
    token = create_access_token(42)

    assert decode_access_token(token) == 42


def test_an_expired_token_decodes_to_none() -> None:
    issued_in_the_past = datetime.now(UTC) - timedelta(
        minutes=settings.access_token_expire_minutes + 1
    )

    token = create_access_token(1, now=issued_in_the_past)

    assert decode_access_token(token) is None


def test_a_token_signed_with_a_different_key_decodes_to_none() -> None:
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": "1",
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        },
        "a-completely-different-signing-key-not-the-real-one",
        algorithm=JWT_ALGORITHM,
    )

    assert decode_access_token(forged) is None


def test_an_alg_none_token_decodes_to_none() -> None:
    """`{"alg": "none"}` needs no signature at all — pinning `algorithms=` in
    `decode_access_token` is what stands between this and a forged admin
    token.
    """
    now = datetime.now(UTC)
    unsigned = jwt.encode(
        {
            "sub": "1",
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        },
        key="",
        algorithm="none",
    )

    assert decode_access_token(unsigned) is None


def test_a_non_integer_subject_decodes_to_none() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "not-an-id",
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        },
        settings.jwt_secret_key,
        algorithm=JWT_ALGORITHM,
    )

    assert decode_access_token(token) is None


def test_a_token_missing_exp_decodes_to_none() -> None:
    token = jwt.encode(
        {"sub": "1", "iat": datetime.now(UTC)},
        settings.jwt_secret_key,
        algorithm=JWT_ALGORITHM,
    )

    assert decode_access_token(token) is None


@pytest.mark.parametrize("garbage", ["", "not-a-jwt-at-all", "a.b.c"])
def test_garbage_input_decodes_to_none(garbage: str) -> None:
    assert decode_access_token(garbage) is None
