import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, Optional
import uuid


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskProgress:
    task_id: str
    status: TaskStatus
    channel_id: str
    operation: str  # "fetch" or "download"
    current: int = 0
    total: int = 0
    message: str = ""
    error: Optional[str] = None


@dataclass
class Task:
    task_id: str
    channel_id: str
    operation: str
    progress: TaskProgress = field(default=None)
    _queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    _cancelled: bool = field(default=False)

    def __post_init__(self):
        self.progress = TaskProgress(
            task_id=self.task_id,
            status=TaskStatus.PENDING,
            channel_id=self.channel_id,
            operation=self.operation,
        )

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self):
        self._cancelled = True

    async def update(self, current: int = None, total: int = None, message: str = None, status: TaskStatus = None):
        if self._cancelled:
            raise CancelledError("Task was cancelled")
        if current is not None:
            self.progress.current = current
        if total is not None:
            self.progress.total = total
        if message is not None:
            self.progress.message = message
        if status is not None:
            self.progress.status = status
        await self._queue.put(self.progress)

    async def complete(self, message: str = "Completed"):
        self.progress.status = TaskStatus.COMPLETED
        self.progress.message = message
        await self._queue.put(self.progress)

    async def fail(self, error: str):
        self.progress.status = TaskStatus.FAILED
        self.progress.error = error
        self.progress.message = f"Error: {error}"
        await self._queue.put(self.progress)

    async def set_cancelled(self, message: str = "Cancelled by user"):
        self.progress.status = TaskStatus.CANCELLED
        self.progress.message = message
        await self._queue.put(self.progress)

    async def events(self) -> AsyncGenerator[TaskProgress, None]:
        while True:
            progress = await self._queue.get()
            yield progress
            if progress.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                break


class CancelledError(Exception):
    pass


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def create_task(self, channel_id: str, operation: str) -> Task:
        task_id = str(uuid.uuid4())[:8]
        task = Task(task_id=task_id, channel_id=channel_id, operation=operation)
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def get_active_task(self, channel_id: str, operation: str) -> Optional[Task]:
        for task in self._tasks.values():
            if (task.channel_id == channel_id
                and task.operation == operation
                and task.progress.status == TaskStatus.RUNNING):
                return task
        return None

    def cleanup_completed(self):
        to_remove = [
            tid for tid, task in self._tasks.items()
            if task.progress.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        ]
        for tid in to_remove:
            del self._tasks[tid]


task_manager = TaskManager()
