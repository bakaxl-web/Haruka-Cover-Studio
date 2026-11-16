"""任务存储与执行。

每个任务一个输出目录，状态机为 queued → running → succeeded/failed/cancelled。
任务执行放在后台线程，引擎通过 JobContext 上报阶段、进度与日志。
"""
from __future__ import annotations

import json
import secrets
import threading
import traceback
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import config

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class JobNotFoundError(KeyError):
    """任务不存在。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_job_id() -> str:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{secrets.token_hex(3)}"


class JobContext:
    """引擎执行时使用的上下文：上报阶段、写日志、检查取消。"""

    def __init__(self, store: "JobStore", job_id: str):
        self._store = store
        self.job_id = job_id

    @property
    def cancel_requested(self) -> bool:
        return bool(self._store.get(self.job_id).get("cancel_requested"))

    def update(self, **fields) -> None:
        self._store.update(self.job_id, **fields)

    def stage(self, name: str, progress: float | None = None) -> None:
        fields = {"stage": name}
        if progress is not None:
            fields["progress"] = max(0.0, min(1.0, float(progress)))
        self.update(**fields)

    def log(self, message: str) -> None:
        self._store.append_log(self.job_id, message)


class JobStore:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._pending = deque()
        self._scheduled: set[str] = set()
        self._worker: threading.Thread | None = None
        # 重启后恢复已保存的作品；中断的任务只标为失败，不自动重新占用 GPU。
        for record in self.output_root.glob("*/job.json"):
            try:
                job = json.loads(record.read_text(encoding="utf-8"))
                if job.get("id") != record.parent.name:
                    continue
                if job.get("status") not in TERMINAL_STATUSES:
                    job.update(status="failed", stage="failed", error="应用退出时任务尚未完成，请重新提交。")
                self._jobs[job["id"]] = job
            except (OSError, ValueError):
                continue

    # ---- 任务管理 ----
    def create(self, request: dict) -> dict:
        with self._lock:
            job_id = _new_job_id()
            while job_id in self._jobs or (self.output_root / job_id).exists():
                job_id = _new_job_id()
            job_dir = self.output_root / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            job = {
                "id": job_id,
                "status": "queued",
                "stage": "queued",
                "progress": 0.0,
                "created_at": _now(),
                "updated_at": _now(),
                "request": deepcopy(request),
                "artifacts": [],
                "error": None,
                "cancel_requested": False,
                "output_dir": str(job_dir),
                "log_path": str(job_dir / "job.log"),
            }
            (job_dir / "job.log").touch()
            self._jobs[job_id] = job
            self._persist(job_id)
            return deepcopy(job)

    def get(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return deepcopy(job)

    def list_all(self) -> list[dict]:
        with self._lock:
            jobs = [dict(job) for job in self._jobs.values()]
        jobs.sort(key=lambda item: item["created_at"], reverse=True)
        return jobs

    def update(self, job_id: str, **fields) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            job.update(fields)
            job["updated_at"] = _now()
            self._persist(job_id)
            return dict(job)

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            job["cancel_requested"] = True
            if job["status"] == "queued":
                job["status"] = "cancelled"
                job["stage"] = "cancelled"
                job["updated_at"] = _now()
                self._persist(job_id)
            return dict(job)

    def append_log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            path = Path(job["log_path"])
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(message.rstrip("\n") + "\n")
        except OSError:
            # 日志写入失败不应中断任务本身
            pass

    def log_tail(self, job_id: str, max_lines: int = 80) -> list[str]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            path = Path(job["log_path"])
        if not path.is_file():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return lines[-max_lines:] if max_lines > 0 else []

    def _persist(self, job_id: str) -> None:
        job = self._jobs[job_id]
        target = Path(job["output_dir"]) / "job.json"
        payload = dict(job)
        try:
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---- 执行 ----
    def start(self, job_id: str, runner: Callable[[dict, JobContext], list[dict]]) -> None:
        # 每个存储仅有一个消费线程，队列任务不各自占用线程或推理资源。
        with self._lock:
            if self.get(job_id)["status"] != "queued" or job_id in self._scheduled:
                return
            self._scheduled.add(job_id)
            self._pending.append((job_id, runner))
            if self._worker is None:
                self._worker = threading.Thread(target=self._consume, daemon=True, name="inference-queue")
                self._worker.start()

    def _consume(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._worker = None
                    return
                job_id, runner = self._pending.popleft()
                if self._jobs[job_id]["status"] != "queued":
                    self._scheduled.discard(job_id)
                    continue
                self.update(job_id, status="running", stage="starting", progress=0.0)
            self._run(job_id, runner)

    def _run(self, job_id: str, runner: Callable[[dict, JobContext], list[dict]]) -> None:
        context = JobContext(self, job_id)
        try:
            if context.cancel_requested:
                self.update(job_id, status="cancelled", stage="cancelled")
                return
            artifacts = runner(self.get(job_id), context) or []
            if context.cancel_requested:
                self.update(job_id, status="cancelled", stage="cancelled")
                return
            self.update(job_id, status="succeeded", stage="done", progress=1.0, artifacts=artifacts)
        except Exception as error:  # noqa: BLE001 - 任务失败必须落盘并呈现给用户
            self.append_log(job_id, traceback.format_exc())
            if context.cancel_requested:
                self.update(job_id, status="cancelled", stage="cancelled")
            else:
                self.update(job_id, status="failed", stage="failed", error=str(error))
        finally:
            with self._lock:
                self._scheduled.discard(job_id)


store = JobStore(config.OUTPUT_ROOT)
