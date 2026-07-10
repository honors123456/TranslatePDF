"""内存态翻译任务管理：创建、执行、进度、取消。

任务状态只存内存（自用定位，重启即失），不引入数据库。
"""

import asyncio
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .clean_pdf import clean_outputs

from pdf2zh_next.config.model import (
    PDFSettings,
    SettingsModel,
    TranslationSettings,
)
from pdf2zh_next.high_level import do_translate_async_stream

from .engines import EngineConfig, build_engine_settings

logger = logging.getLogger(__name__)


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
    upload_dir: Path | None = None  # 源文件所在目录，翻译结束后清理
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
    def __init__(
        self,
        output_root: Path,
        upload_root: Path,
        max_concurrent: int = 2,
        retention_seconds: int = 2 * 3600,
        gc_interval: int = 600,
    ):
        self.output_root = output_root
        self.upload_root = upload_root
        self.retention_seconds = retention_seconds
        self.gc_interval = gc_interval
        self.tasks: dict[str, Task] = {}
        self._sem = asyncio.Semaphore(max_concurrent)
        self._gc_task: asyncio.Task | None = None

    def create(
        self,
        pdf_path: Path,
        engine: EngineConfig,
        lang_in: str,
        lang_out: str,
        pages: str | None,
    ) -> Task:
        task = Task(
            id=uuid.uuid4().hex[:12],
            filename=pdf_path.name,
            upload_dir=pdf_path.parent,
        )
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
                qps=20,
                no_auto_extract_glossary=True,
            ),
            pdf=PDFSettings(
                pages=pages,
                watermark_output_mode="no_watermark",
            ),
            translate_engine_settings=build_engine_settings(engine),
        )

    async def _run(self, task: Task, settings: SettingsModel, pdf_path: Path) -> None:
        try:
            task.stage = "排队中"  # 等待并发闸期间前端展示
            async with self._sem:  # 并发闸：同时翻译的任务数受限，其余在此排队
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
                        # 后处理：清除上游遗留的控制字符
                        clean_outputs(task.mono_path, task.dual_path)
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
            # 源文件翻译后已无用，立即清理；输出目录保留供下载，交给 GC
            _safe_rmtree(task.upload_dir)

    # ---------- Housekeeping：启动清理 + 后台 GC ----------

    def startup_cleanup(self) -> None:
        """服务启动时清空 uploads/outputs 遗留目录。

        内存态 tasks 重启即空，磁盘上的旧目录已无法通过界面访问，全是孤儿。
        """
        for root in (self.upload_root, self.output_root):
            if not root.exists():
                continue
            for child in root.iterdir():
                _safe_rmtree(child)

    def _gc_once(self) -> None:
        """清理已完成且超过保留期的任务：内存记录 + 磁盘目录。"""
        now = time.time()
        for task_id, task in list(self.tasks.items()):
            if task.status == "running" or task.finished_at is None:
                continue
            if now - task.finished_at <= self.retention_seconds:
                continue
            self.tasks.pop(task_id, None)
            _safe_rmtree(self.output_root / task_id)
            _safe_rmtree(task.upload_dir)

    async def _gc_loop(self) -> None:
        while True:
            await asyncio.sleep(self.gc_interval)
            try:
                self._gc_once()
            except Exception as exc:  # 单轮异常不中断循环
                logger.warning("gc round failed: %s", exc)

    def start_gc(self) -> None:
        if self._gc_task is None or self._gc_task.done():
            self._gc_task = asyncio.create_task(self._gc_loop())

    def stop_gc(self) -> None:
        if self._gc_task is not None:
            self._gc_task.cancel()
            self._gc_task = None


def _safe_rmtree(path: Path | None) -> None:
    """删除目录（含内容），None/不存在直接返回。集中所有删除便于审计。"""
    if path is None or not path.exists():
        return
    shutil.rmtree(path, ignore_errors=True)
