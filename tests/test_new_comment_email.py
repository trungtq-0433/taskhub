"""The new-comment email's text, from its template: plain, unescaped, and user
text is printed as typed — never escaped as HTML, never run as a template."""

from app.notifications.comment import new_comment_email


def test_user_text_reaches_the_email_as_typed() -> None:
    email = new_comment_email(
        to="worker@example.com",
        author="ann",
        task_id=7,
        task_title='Fix <b> & "quotes"',
        comment_id=42,
        content="Looks fine.\n{{ 7 * 7 }} {% if true %}x{% endif %}",
    )

    assert email.subject == "[TaskHub] New comment on task #7"
    assert email.body == (
        'ann commented on task #7 "Fix <b> & "quotes"":\n\n'
        "Looks fine.\n{{ 7 * 7 }} {% if true %}x{% endif %}"
    )
