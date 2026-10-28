"""The email a task's assignee gets when someone comments on the task.

Who gets it, and when, is `CommentService`'s call; this module only says what
it reads. It takes plain values, so what it returns holds no ORM object (see
`app.core.mail`).
"""

from app.core.mail import OutgoingEmail
from app.notifications.rendering import load_template

_BODY = load_template("new_comment.txt")


def new_comment_email(
    *, to: str, author: str, task_id: int, task_title: str, comment_id: int, content: str
) -> OutgoingEmail:
    return OutgoingEmail(
        to=to,
        # Set here, not in a template: ids only, because client text (a title
        # may hold CR/LF) must stay out of headers.
        subject=f"[TaskHub] New comment on task #{task_id}",
        body=_BODY.render(author=author, task_id=task_id, task_title=task_title, content=content),
        reference=f"task {task_id}, comment {comment_id}",
    )
