"""Two assigns to the same user, on real connections: the row lock is what
makes the second one see the first and record nothing (one real change, one
history row).

`db_session` cannot hold two transactions (one connection, savepoints), so
these use `committing_sessions`. Ordering is proven from server state
(`pg_blocking_pids`), never from `sleep`.
"""

import asyncio
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import UnauthorizedError
from app.models import Project, Task, User, task_assignment
from app.repositories.task import TaskRepository
from app.services.task import TaskService
from tests.factories import make_user

Factory = async_sessionmaker[AsyncSession]

BLOCKED_BY = text(
    "SELECT count(*) FROM pg_stat_activity"
    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
    " AND :holder = ANY(pg_blocking_pids(pid))"
)


@dataclass(frozen=True)
class Seeded:
    task: int
    a: int
    b: int
    c: int


@pytest.fixture
async def seeded(committing_sessions: Factory) -> Seeded:
    async with committing_sessions() as session:
        a, b, c = make_user("lock-a"), make_user("lock-b"), make_user("lock-c")
        project = Project(name="Lock holder")
        session.add_all([a, b, c, project])
        await session.flush()
        task = Task(title="Contended", project_id=project.id, assignee_id=a.id)
        session.add(task)
        await session.commit()
        return Seeded(task=task.id, a=a.id, b=b.id, c=c.id)


async def _wait_until_blocked(
    observer: AsyncSession, holder_pid: int, tx2: "asyncio.Task[Task]", deadline: float = 5
) -> None:
    async with asyncio.timeout(deadline):
        while True:
            if tx2.done():
                tx2.result()  # re-raises tx2's own failure first
                raise AssertionError("assign did not wait for the row lock")
            if await observer.scalar(BLOCKED_BY, {"holder": holder_pid}):
                return
            await observer.rollback()
            await asyncio.sleep(0.01)


async def _cancel_and_wait(task: "asyncio.Task[Task]") -> None:
    if not task.done():
        task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _history(factory: Factory, task_id: int) -> list[tuple[int | None, int]]:
    async with factory() as reader:
        rows = await reader.execute(
            select(task_assignment.c.assignee_id, task_assignment.c.assigned_by_id)
            .where(task_assignment.c.task_id == task_id)
            .order_by(task_assignment.c.id)
        )
        return [(row[0], row[1]) for row in rows.all()]


async def _hold_lock(
    stack: AsyncExitStack, factory: Factory, task_id: int
) -> tuple[AsyncSession, int]:
    s1 = factory()
    stack.push_async_callback(s1.close)
    stack.push_async_callback(s1.rollback)
    holder_pid = await s1.scalar(text("SELECT pg_backend_pid()"))
    assert holder_pid is not None
    assert await TaskRepository(s1).get_for_update(task_id) is not None
    return s1, holder_pid


async def _assign_to_b_by_hand(s1: AsyncSession, seeded: Seeded) -> None:
    await s1.execute(update(Task).where(Task.id == seeded.task).values(assignee_id=seeded.b))
    await s1.execute(
        insert(task_assignment).values(
            task_id=seeded.task,
            assignee_id=seeded.b,
            assigned_by_id=seeded.a,
        )
    )
    await s1.commit()


async def _run_duplicate_assign(
    committing_sessions: Factory, seeded: Seeded, *, preload: bool
) -> None:
    async with asyncio.timeout(15), AsyncExitStack() as stack:
        s1, holder_pid = await _hold_lock(stack, committing_sessions, seeded.task)
        s2, observer = committing_sessions(), committing_sessions()
        stack.push_async_callback(s2.close)
        stack.push_async_callback(observer.close)
        if preload:
            # Keep the reference: the identity map is weak, and a collected
            # object would make this test pass without `populate_existing`.
            preloaded = await s2.get(Task, seeded.task)
            assert preloaded is not None and preloaded.assignee_id == seeded.a
        tx2 = asyncio.create_task(
            TaskService(s2).assign(seeded.task, assignee_id=seeded.b, assigned_by_id=seeded.c)
        )
        stack.push_async_callback(_cancel_and_wait, tx2)

        await _wait_until_blocked(observer, holder_pid, tx2)
        assert not tx2.done()

        await _assign_to_b_by_hand(s1, seeded)
        result = await asyncio.wait_for(tx2, 5)

        # tx2 saw the committed B and no-opped: only s1's row exists.
        assert await _history(committing_sessions, seeded.task) == [(seeded.b, seeded.a)]
        assert result.assignee is not None
        assert result.assignee.id == seeded.b


async def test_a_second_assign_to_the_same_user_waits_for_the_lock_and_records_no_second_row(
    committing_sessions: Factory, seeded: Seeded
) -> None:
    await _run_duplicate_assign(committing_sessions, seeded, preload=False)


async def test_a_preloaded_task_is_refreshed_under_the_lock_so_the_duplicate_assign_is_a_no_op(
    committing_sessions: Factory, seeded: Seeded
) -> None:
    await _run_duplicate_assign(committing_sessions, seeded, preload=True)


async def test_a_held_assign_lock_does_not_block_a_bookmark_on_the_same_task(
    committing_sessions: Factory, seeded: Seeded
) -> None:
    async with asyncio.timeout(15), AsyncExitStack() as stack:
        await _hold_lock(stack, committing_sessions, seeded.task)
        s2 = committing_sessions()
        stack.push_async_callback(s2.close)

        await asyncio.wait_for(TaskService(s2).bookmark(seeded.task, user_id=seeded.b), 2)


async def test_assign_reports_an_unauthorized_caller_when_the_caller_was_deleted(
    committing_sessions: Factory, seeded: Seeded
) -> None:
    async with committing_sessions() as deleting:
        await deleting.execute(delete(User).where(User.id == seeded.c))
        await deleting.commit()

    async with committing_sessions() as assigning:
        with pytest.raises(UnauthorizedError) as raised:
            await TaskService(assigning).assign(
                seeded.task, assignee_id=seeded.b, assigned_by_id=seeded.c
            )
    assert raised.value.problem_type == "unauthorized"

    async with committing_sessions() as reader:
        task = await reader.get(Task, seeded.task)
        assert task is not None
        assert task.assignee_id == seeded.a
    assert await _history(committing_sessions, seeded.task) == []
