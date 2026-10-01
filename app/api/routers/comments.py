"""Comment endpoints: add one to a task, delete one."""

from fastapi import APIRouter, status

from app.api.auth import ActiveUserDep
from app.api.params import ErrorResponses, IdPath, not_found
from app.api.permissions import CommentModifierDep
from app.api.routers.tasks import INACTIVE_USER, TASK_NOT_FOUND
from app.api.routers.users import UNAUTHORIZED
from app.core.handlers import PROBLEM_CONTENT
from app.schemas.comment import CommentCreate, CommentRead
from app.services.comment import CommentServiceDep

router = APIRouter(tags=["comments"])

COMMENT_FORBIDDEN: ErrorResponses = {
    403: {
        "content": PROBLEM_CONTENT,
        "description": "Disabled account, or not the comment's author, an admin or the owner",
    }
}


@router.post(
    "/tasks/{task_id}/comments",
    summary="Comment on a task",
    status_code=status.HTTP_201_CREATED,
    responses={**UNAUTHORIZED, **INACTIVE_USER, **TASK_NOT_FOUND},
)
async def create_comment(
    task_id: IdPath, payload: CommentCreate, user: ActiveUserDep, service: CommentServiceDep
) -> CommentRead:
    """Any signed-in user may comment. The author is the caller; `content` is
    trimmed and must be 1 to 5,000 characters afterwards."""
    return CommentRead.model_validate(await service.create(task_id, payload, author=user))


@router.delete(
    "/tasks/{task_id}/comments/{comment_id}",
    summary="Delete a comment",
    status_code=status.HTTP_204_NO_CONTENT,
    response_description="Deleted; no body",
    responses={**UNAUTHORIZED, **COMMENT_FORBIDDEN, **not_found("task or comment")},
)
async def delete_comment(comment: CommentModifierDep, service: CommentServiceDep) -> None:
    """Only the comment's author, an administrator or the project's owner. A
    missing task or comment is 404 before any permission is checked. Permanent;
    there is no undo."""
    await service.delete(task_id=comment.task_id, comment_id=comment.id)
