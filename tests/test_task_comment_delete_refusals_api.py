"""`DELETE /tasks/{task_id}/comments/{comment_id}`: refusals that need no permission rule.

Split from `test_task_comment_delete_api.py`, which holds the success and
authorization cases, to stay under the file-size ceiling.
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MAX_ID
from tests.factories import auth_headers
from tests.test_task_comment_delete_api import comment_exists, comment_url, seed_comment


@pytest.mark.parametrize(
    ("task_id", "comment_id"), [(0, 1), (MAX_ID + 1, 1), (1, 0), (1, MAX_ID + 1)]
)
async def test_an_out_of_range_task_or_comment_id_is_422_validation(
    db_session: AsyncSession, api_client: AsyncClient, task_id: int, comment_id: int
) -> None:
    author, _, _, _ = await seed_comment(db_session)

    response = await api_client.delete(
        comment_url(task_id, comment_id), headers=auth_headers(author)
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("validation")


async def test_deleting_without_a_token_is_401(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    _, _, task, comment = await seed_comment(db_session)

    response = await api_client.delete(comment_url(task.id, comment.id))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_a_disabled_author_cannot_delete_their_own_comment_403_inactive_user(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    author, _, task, comment = await seed_comment(db_session)
    author.is_active = False
    await db_session.flush()

    response = await api_client.delete(
        comment_url(task.id, comment.id), headers=auth_headers(author)
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("inactive-user")
    assert await comment_exists(db_session, comment.id)
