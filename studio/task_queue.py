"""
任务队列。
- TaskQueue: 线程安全队列(用 PySide6 信号通信,避免线程同步)
- Scheduler: 把 task 派发给最合适的账号(配额最多 + backend 匹配)
- 持久化:队列 + 历史 → ~/.doubao-studio/queue.json
"""
from __future__ import annotations
from typing import List, Optional, Callable, Dict
from pathlib import Path
from dataclasses import asdict
import json, time, threading

from PySide6.QtCore import QObject, Signal, QTimer

from .models import (
    GenerationTask, Account,
    TASK_PENDING, TASK_RUNNING, TASK_AWAITING, TASK_DONE, TASK_FAILED, TASK_CANCELED,
    TASK_TYPE_IMAGE, TASK_TYPE_VIDEO,
    dict_to_dataclass,
)
from . import storage as ST


QUEUE_FILE = ST.APP_DIR / "queue.json"
HISTORY_LIMIT = 200


class TaskQueue(QObject):
    """全局单例。维护待执行 + 运行中 + 历史 三段。"""
    changed = Signal()             # 任意状态变化都发这个

    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()
        self.tasks: List[GenerationTask] = []   # 全部任务(队列 + 运行中 + 已完成)
        self._load()

    # ---- 持久化 ----
    def _load(self):
        if not QUEUE_FILE.exists(): return
        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            self.tasks = [dict_to_dataclass(GenerationTask, x) for x in data]
            # 启动时把"running"任务重置为 pending(进程被杀过)
            for t in self.tasks:
                if t.status in (TASK_RUNNING, TASK_AWAITING):
                    t.status = TASK_PENDING
                    t.account_id = ""
        except Exception as e:
            print(f"加载队列失败: {e}")

    def _save(self):
        try:
            QUEUE_FILE.write_text(
                json.dumps([asdict(t) for t in self.tasks[-HISTORY_LIMIT:]],
                           ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"保存队列失败: {e}")

    # ---- 操作 ----
    def enqueue(self, task: GenerationTask) -> GenerationTask:
        with self._lock:
            task.status = TASK_PENDING
            self.tasks.append(task)
            self._save()
        self.changed.emit()
        return task

    def cancel(self, task_id: str):
        with self._lock:
            for t in self.tasks:
                if t.id == task_id and t.status in (TASK_PENDING, TASK_AWAITING):
                    t.status = TASK_CANCELED
                    self._save()
                    break
        self.changed.emit()

    def mark_running(self, task_id: str, account_id: str):
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    t.status = TASK_RUNNING
                    t.account_id = account_id
                    t.started_at = time.time()
                    self._save()
                    break
        self.changed.emit()

    def mark_awaiting(self, task_id: str):
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    t.status = TASK_AWAITING
                    self._save()
                    break
        self.changed.emit()

    def mark_done(self, task_id: str, result_files: List[str] = None, result_text: str = ""):
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    t.status = TASK_DONE
                    t.finished_at = time.time()
                    t.result_files = result_files or []
                    t.result_text = result_text or ""
                    self._save()
                    break
        self.changed.emit()

    def mark_failed(self, task_id: str, error: str):
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    t.status = TASK_FAILED
                    t.error = error
                    t.finished_at = time.time()
                    self._save()
                    break
        self.changed.emit()

    def clear_history(self):
        with self._lock:
            self.tasks = [t for t in self.tasks
                          if t.status in (TASK_PENDING, TASK_RUNNING, TASK_AWAITING)]
            self._save()
        self.changed.emit()

    # ---- 查询 ----
    def pending(self) -> List[GenerationTask]:
        with self._lock:
            return [t for t in self.tasks if t.status == TASK_PENDING]

    def active(self) -> List[GenerationTask]:
        with self._lock:
            return [t for t in self.tasks
                    if t.status in (TASK_RUNNING, TASK_AWAITING)]

    def recent(self, limit: int = 30) -> List[GenerationTask]:
        with self._lock:
            return list(reversed(self.tasks[-limit:]))


# ---- Scheduler ----
def pick_account(task: GenerationTask, accounts: List[Account]) -> Optional[Account]:
    """选最合适的账号:同 backend + 剩余配额最多 + 未在执行中。"""
    candidates = [a for a in accounts
                  if a.backend_id == task.backend_id and a.remaining() > 0]
    if not candidates: return None
    candidates.sort(key=lambda a: a.remaining(), reverse=True)
    return candidates[0]


# ---- 单例 ----
_queue_singleton: Optional[TaskQueue] = None

def get_queue() -> TaskQueue:
    global _queue_singleton
    if _queue_singleton is None:
        _queue_singleton = TaskQueue()
    return _queue_singleton
