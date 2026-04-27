"""
轻量任务控制信号层 — 暂停/恢复/取消。

每个任务（conv_id 或 score_{conv_id}）一个 TaskControl 实例。
生成循环和打分循环在每轮开始前调用 checkpoint()，
若处于暂停态则阻塞，若已取消则抛 CancelledError。

技术选型依据（GitHub 社区最佳实践）：
  - asyncio.Event 实现暂停/恢复（标准模式）
  - 显式 cancelled 标志 + Event.set() 解除阻塞实现取消
  - 不引入 Celery/ARQ 等外部队列，保持单进程轻量
"""
from __future__ import annotations

import asyncio
from typing import Callable, Awaitable


class TaskControl:
    """单任务的暂停/恢复/取消控制器。"""

    def __init__(self, task_id: str = ""):
        self.task_id = task_id
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 默认运行态
        self._cancelled = False
        self.status: str = "running"  # running / paused / cancelled / completed

    async def checkpoint(self) -> None:
        """
        每轮开始前调用。

        - 若已取消：抛出 asyncio.CancelledError
        - 若已暂停：阻塞等待恢复
        """
        if self._cancelled:
            raise asyncio.CancelledError(f"任务 {self.task_id} 被用户取消")
        await self._pause_event.wait()
        # 恢复后再检查一次取消（防止暂停期间取消）
        if self._cancelled:
            raise asyncio.CancelledError(f"任务 {self.task_id} 在暂停期间被取消")

    def pause(self) -> None:
        """暂停任务。当前轮次执行完毕后，下一轮开始前阻塞。"""
        if self._cancelled:
            return
        self._pause_event.clear()
        self.status = "paused"

    def resume(self) -> None:
        """恢复已暂停的任务。"""
        if self._cancelled:
            return
        self._pause_event.set()
        self.status = "running"

    def cancel(self) -> None:
        """取消任务。若正在暂停则先解除阻塞再取消。"""
        self._cancelled = True
        self._pause_event.set()  # 解除暂停阻塞以便退出
        self.status = "cancelled"

    def complete(self) -> None:
        """标记任务完成。"""
        self.status = "completed"

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set() and not self._cancelled


# ═══ 全局注册表 ═══

_controls: dict[str, TaskControl] = {}


def get_or_create(task_id: str) -> TaskControl:
    """获取或创建任务控制器。"""
    if task_id not in _controls:
        _controls[task_id] = TaskControl(task_id)
    return _controls[task_id]


def get(task_id: str) -> TaskControl | None:
    """获取已有的任务控制器，不存在返回 None。"""
    return _controls.get(task_id)


def remove(task_id: str) -> None:
    """移除任务控制器。"""
    _controls.pop(task_id, None)


def list_active() -> dict[str, str]:
    """返回所有活跃任务及其状态。"""
    return {tid: ctrl.status for tid, ctrl in _controls.items()}


def cancel_all() -> int:
    """取消所有活跃任务（用于优雅关闭）。返回取消数量。"""
    count = 0
    for ctrl in _controls.values():
        if ctrl.status in {"running", "paused"}:
            ctrl.cancel()
            count += 1
    return count
