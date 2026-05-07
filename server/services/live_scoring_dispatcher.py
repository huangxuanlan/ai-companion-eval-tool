from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Awaitable, Callable

import database as db
from services import task_control


@dataclass(slots=True)
class LiveScoringJob:
    conversation_id: str
    turn: int
    config: dict | None = None


class LiveScoringDispatcher:
    """全局 live scoring 调度器。

    规则：
    - 同一 conversation 串行
    - 不同 conversation 共享全局池
    - turn 已 settled 或已在队列/运行中时丢弃重复提交
    """

    def __init__(
        self,
        *,
        worker: Callable[[str, int, dict | None], Awaitable[dict | None]],
        get_max_workers: Callable[[], int],
    ) -> None:
        self._worker = worker
        self._get_max_workers = get_max_workers
        self._lock = asyncio.Lock()
        self._queues: dict[str, deque[LiveScoringJob]] = {}
        self._queue_order: deque[str] = deque()
        self._queued_turns: set[tuple[str, int]] = set()
        self._running_turns: set[tuple[str, int]] = set()
        self._active_conversations: set[str] = set()
        self._active_limit_groups: dict[str, int] = {}
        self._active_tasks: set[asyncio.Task] = set()
        self._idle_event = asyncio.Event()
        self._idle_event.set()

    def _task_id(self, conv_id: str) -> str:
        return f"live_score_{conv_id}"

    @staticmethod
    def _control_status(ctrl) -> str:
        return str(getattr(ctrl, "status", "") or "").strip().lower()

    @staticmethod
    def _invoke_control(ctrl, action: str) -> bool:
        method = getattr(ctrl, action, None)
        if not callable(method):
            return False
        method()
        return True

    def _is_turn_settled(self, conv_id: str, turn: int) -> bool:
        conversation = db.get_conversation(conv_id)
        if not conversation:
            return True
        target = next(
            (item for item in conversation.get("results", []) if int(item.get("turn", 0) or 0) == turn),
            None,
        )
        if not target:
            return True
        status = str(target.get("score_status", "unscored") or "unscored").strip().lower()
        return status in {"scored", "failed", "skipped"}

    async def enqueue(self, conv_id: str, turn: int, config: dict | None = None) -> bool:
        conv_id = str(conv_id or "").strip()
        turn = int(turn or 0)
        if not conv_id or turn <= 0:
            return False
        if self._is_turn_settled(conv_id, turn):
            return False

        async with self._lock:
            task_id = self._task_id(conv_id)
            ctrl = task_control.get(task_id)
            if ctrl is None or self._control_status(ctrl) in {"cancelled", "completed"}:
                task_control.remove(task_id)
                task_control.get_or_create(task_id)
            key = (conv_id, turn)
            if key in self._queued_turns or key in self._running_turns:
                return False
            queue = self._queues.setdefault(conv_id, deque())
            queue.append(
                LiveScoringJob(
                    conversation_id=conv_id,
                    turn=turn,
                    config=deepcopy(config) if config is not None else None,
                )
            )
            self._queued_turns.add(key)
            if conv_id not in self._queue_order:
                self._queue_order.append(conv_id)
            self._idle_event.clear()
            self._schedule_locked()
            return True

    async def enqueue_pending(
        self,
        conv_id: str,
        turns: list[int] | tuple[int, ...],
        config: dict | None = None,
    ) -> int:
        enqueued = 0
        for turn in turns or []:
            if await self.enqueue(conv_id, int(turn or 0), config=config):
                enqueued += 1
        return enqueued

    def has_activity(self, conv_id: str) -> bool:
        conv_id = str(conv_id or "").strip()
        if not conv_id:
            return False
        queue = self._queues.get(conv_id) or ()
        return bool(queue) or conv_id in self._active_conversations

    def is_conversation_active(self, conv_id: str) -> bool:
        conv_id = str(conv_id or "").strip()
        if not conv_id:
            return False
        return conv_id in self._active_conversations

    def get_queue_size(self, conv_id: str) -> int:
        conv_id = str(conv_id or "").strip()
        if not conv_id:
            return 0
        return len(self._queues.get(conv_id) or ())

    async def pause_conversation(self, conv_id: str) -> None:
        conv_id = str(conv_id or "").strip()
        if not conv_id:
            return
        task_id = self._task_id(conv_id)
        ctrl = task_control.get(task_id)
        if ctrl is None:
            ctrl = task_control.get_or_create(task_id)
        self._invoke_control(ctrl, "pause")

    async def resume_conversation(self, conv_id: str) -> None:
        conv_id = str(conv_id or "").strip()
        if not conv_id:
            return
        task_id = self._task_id(conv_id)
        ctrl = task_control.get(task_id)
        if ctrl is None or self._control_status(ctrl) == "cancelled":
            task_control.remove(task_id)
            ctrl = task_control.get_or_create(task_id)
        self._invoke_control(ctrl, "resume")
        async with self._lock:
            self._schedule_locked()

    async def cancel_conversation(self, conv_id: str) -> None:
        conv_id = str(conv_id or "").strip()
        if not conv_id:
            return
        task_id = self._task_id(conv_id)
        ctrl = task_control.get(task_id)
        if ctrl is None:
            ctrl = task_control.get_or_create(task_id)
        if not self._invoke_control(ctrl, "cancel"):
            task_control.remove(task_id)
        async with self._lock:
            queue = self._queues.pop(conv_id, deque())
            for job in queue:
                self._queued_turns.discard((job.conversation_id, job.turn))
            self._queue_order = deque(item for item in self._queue_order if item != conv_id)
            if not self._active_tasks and not self._queued_turns:
                self._idle_event.set()

    async def notify_capacity_changed(self) -> None:
        async with self._lock:
            self._schedule_locked()

    @staticmethod
    def _coerce_worker_limit(value) -> int | None:
        if value is None:
            return None
        try:
            return max(1, min(int(value), 24))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _job_limit_group(job: LiveScoringJob) -> str:
        runtime = dict((job.config or {}).get("runtime", {}) or {})
        for key in ("ab_session_id", "orchestration_run_id", "batch_run_id"):
            value = str(runtime.get(key, "") or "").strip()
            if value:
                return f"{key}:{value}"
        return ""

    @classmethod
    def _job_worker_limit(cls, job: LiveScoringJob) -> int | None:
        runtime = dict((job.config or {}).get("runtime", {}) or {})
        return cls._coerce_worker_limit(runtime.get("scoring_max_workers"))

    def _group_has_capacity(self, job: LiveScoringJob) -> bool:
        group = self._job_limit_group(job)
        if not group:
            return True
        limit = self._job_worker_limit(job)
        if limit is None:
            return True
        return self._active_limit_groups.get(group, 0) < limit

    async def wait_for_idle(self, timeout: float = 10.0) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(timeout, 0.1)
        while True:
            async with self._lock:
                idle = not self._queued_turns and not self._active_tasks
                if idle:
                    self._idle_event.set()
                    return True
                self._idle_event.clear()
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(self._idle_event.wait(), timeout=min(remaining, 0.2))
            except asyncio.TimeoutError:
                continue

    def _schedule_locked(self) -> None:
        capacity = max(1, min(int(self._get_max_workers() or 1), 24))
        while len(self._active_tasks) < capacity and self._queue_order:
            conv_id = self._pick_next_conversation_locked()
            if not conv_id:
                break
            queue = self._queues.get(conv_id)
            if not queue:
                continue
            job = queue.popleft()
            key = (job.conversation_id, job.turn)
            self._queued_turns.discard(key)
            self._running_turns.add(key)
            self._active_conversations.add(conv_id)
            limit_group = self._job_limit_group(job)
            if limit_group:
                self._active_limit_groups[limit_group] = (
                    self._active_limit_groups.get(limit_group, 0) + 1
                )
            task = asyncio.create_task(self._run_job(job))
            self._active_tasks.add(task)
            task.add_done_callback(lambda done, bound_job=job: asyncio.create_task(self._on_job_done(bound_job, done)))
        if not self._active_tasks and not self._queued_turns:
            self._idle_event.set()

    def _pick_next_conversation_locked(self) -> str | None:
        initial_length = len(self._queue_order)
        for _ in range(initial_length):
            conv_id = self._queue_order.popleft()
            queue = self._queues.get(conv_id)
            if not queue:
                self._queues.pop(conv_id, None)
                continue
            ctrl = task_control.get(self._task_id(conv_id))
            if conv_id in self._active_conversations:
                self._queue_order.append(conv_id)
                continue
            if ctrl and bool(getattr(ctrl, "is_cancelled", False)):
                for job in queue:
                    self._queued_turns.discard((job.conversation_id, job.turn))
                self._queues.pop(conv_id, None)
                continue
            if ctrl and bool(getattr(ctrl, "is_paused", False)):
                self._queue_order.append(conv_id)
                continue
            if queue and not self._group_has_capacity(queue[0]):
                self._queue_order.append(conv_id)
                continue
            if queue:
                self._queue_order.append(conv_id)
            return conv_id
        return None

    async def _run_job(self, job: LiveScoringJob) -> None:
        task_id = self._task_id(job.conversation_id)
        ctrl = task_control.get(task_id)
        if ctrl is None or self._control_status(ctrl) == "cancelled":
            task_control.remove(task_id)
            ctrl = task_control.get_or_create(task_id)
        checkpoint = getattr(ctrl, "checkpoint", None)
        if callable(checkpoint):
            await checkpoint()
        if self._is_turn_settled(job.conversation_id, job.turn):
            return
        await self._worker(job.conversation_id, job.turn, job.config)

    async def _on_job_done(self, job: LiveScoringJob, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            try:
                db.log_conversation_event(
                    job.conversation_id,
                    scope="scoring",
                    level="error",
                    event_type="dispatcher_failed",
                    detail={
                        "turn": job.turn,
                        "error": str(exc),
                    },
                )
            except Exception:
                pass
            print(
                f"[WARN] live scoring dispatcher job failed: "
                f"{job.conversation_id} turn {job.turn}: {exc}"
            )
        async with self._lock:
            key = (job.conversation_id, job.turn)
            self._running_turns.discard(key)
            self._active_conversations.discard(job.conversation_id)
            limit_group = self._job_limit_group(job)
            if limit_group:
                next_count = self._active_limit_groups.get(limit_group, 0) - 1
                if next_count > 0:
                    self._active_limit_groups[limit_group] = next_count
                else:
                    self._active_limit_groups.pop(limit_group, None)
            self._active_tasks.discard(task)
            queue = self._queues.get(job.conversation_id)
            if queue and job.conversation_id not in self._queue_order:
                self._queue_order.append(job.conversation_id)
            elif not queue:
                self._queues.pop(job.conversation_id, None)
                self._queue_order = deque(
                    item for item in self._queue_order if item != job.conversation_id
                )
            self._schedule_locked()
