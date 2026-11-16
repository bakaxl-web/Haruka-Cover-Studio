"""开发自检引擎：不生成音频，只推进阶段，用于验证界面与任务框架。

它仅接受 engine="smoke" 的任务，不会出现在声线预设里。
"""
from __future__ import annotations

import time

from ..jobs import JobContext

STAGES = ["probe", "load", "convert", "mix", "validate"]


def run(job: dict, ctx: JobContext) -> list[dict]:
    for index, stage in enumerate(STAGES, start=1):
        if ctx.cancel_requested:
            return []
        ctx.stage(stage, index / (len(STAGES) + 1))
        ctx.log(f"[smoke] 阶段 {stage}")
        time.sleep(0.4)
    ctx.stage("done", 1.0)
    ctx.log("[smoke] 自检任务完成（未生成音频）")
    return []
