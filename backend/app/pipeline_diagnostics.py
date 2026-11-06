"""保留上游 IPC 超时的原始原因，避免清理子进程时被退出码覆盖。"""

import asyncio
import time

from pdf2zh_next.utils import asynchronize

_OriginalCallback = asynchronize.AsyncCallback


class DiagnosticCallback(_OriginalCallback):
    def __init__(self, timeout=None):
        super().__init__(timeout)
        self.last_event = time.monotonic()
        self.last_stage = "准备中"
        self.last_current = None
        self.last_total = None

    def step_callback(self, *args, **kwargs):
        if args and isinstance(args[0], dict):
            event = args[0]
            self.last_event = time.monotonic()
            self.last_stage = event.get("stage") or self.last_stage
            self.last_current = event.get("stage_current", self.last_current)
            self.last_total = event.get("stage_total", self.last_total)
        return super().step_callback(*args, **kwargs)

    async def __anext__(self):
        try:
            return await super().__anext__()
        except asyncio.TimeoutError:
            self.error = TimeoutError(
                f"翻译子进程连续 {self.timeout:g} 秒未返回进度事件；"
                f"最后阶段：{self.last_stage}，段落：{self.last_current}/{self.last_total}，"
                f"距最后事件 {time.monotonic() - self.last_event:.1f} 秒。"
                "已停止子进程；该超时不等于模型请求超时。"
            )
            raise self.error from None


def install():
    asynchronize.AsyncCallback = DiagnosticCallback
