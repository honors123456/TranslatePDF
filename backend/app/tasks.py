"""内存态翻译任务管理：创建、执行、进度、取消。

任务状态只存内存（自用定位，重启即失），不引入数据库。
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pdf2zh_next.config.model import (
    PDFSettings,
    SettingsModel,
    TranslationSettings,
)
from pdf2zh_next.high_level import do_translate_async_stream

from .engines import EngineConfig, build_engine_settings


@dataclass
class Task:
    id: str
    filename: str
    status: str = "running"  # running | done | error | cancelled
    stage: str = ""
    overall_progress: float = 0.0
    error: str | None = None
    mono_path: Path | None = None
    dual_path: Path | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    job: asyncio.Task | None = None

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "stage": self.stage,
            "overall_progress": round(self.overall_progress, 1),
            "error": self.error,
            "has_mono": self.mono_path is not None,
            "has_dual": self.dual_path is not None,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class TaskManager:
    def __init__(self, output_root: Path):
        self.output_root = output_root
        self.tasks: dict[str, Task] = {}

    def create(
        self,
        pdf_path: Path,
        engine: EngineConfig,
        lang_in: str,
        lang_out: str,
        pages: str | None,
    ) -> Task:
        task = Task(id=uuid.uuid4().hex[:12], filename=pdf_path.name)
        settings = self._build_settings(task.id, engine, lang_in, lang_out, pages)
        settings.validate_settings()
        task.job = asyncio.create_task(self._run(task, settings, pdf_path))
        self.tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task is None or task.status != "running" or task.job is None:
            return False
        task.job.cancel()
        return True

    def _build_settings(
        self,
        task_id: str,
        engine: EngineConfig,
        lang_in: str,
        lang_out: str,
        pages: str | None,
    ) -> SettingsModel:
        return SettingsModel(
            translation=TranslationSettings(
                lang_in=lang_in,
                lang_out=lang_out,
                output=str(self.output_root / task_id),
                qps=4,
            ),
            pdf=PDFSettings(
                pages=pages,
                watermark_output_mode="no_watermark",
            ),
            translate_engine_settings=build_engine_settings(engine),
        )

    async def _run(self, task: Task, settings: SettingsModel, pdf_path: Path) -> None:
        try:
            async for event in do_translate_async_stream(settings, pdf_path):
                etype = event.get("type")
                if etype in {"progress_start", "progress_update", "progress_end"}:
                    task.stage = event.get("stage") or task.stage
                    task.overall_progress = event.get("overall_progress") or 0.0
                elif etype == "error":
                    task.status = "error"
                    task.error = str(event.get("error"))
                    break
                elif etype == "finish":
                    result = event["translate_result"]
                    mono = getattr(result, "mono_pdf_path", None)
                    dual = getattr(result, "dual_pdf_path", None)
                    task.mono_path = Path(mono) if mono else None
                    task.dual_path = Path(dual) if dual else None
                    task.overall_progress = 100.0
                    task.status = "done"
                    break
        except asyncio.CancelledError:
            task.status = "cancelled"
        except Exception as exc:  # 管线内部异常统一转任务错误，不让服务崩
            task.status = "error"
            task.error = str(exc)
        finally:
            if task.status == "running":
                task.status = "error"
                task.error = "translation ended without finish event"
            task.finished_at = time.time()
