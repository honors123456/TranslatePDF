"""内存态翻译任务管理：创建、执行、进度、取消。

任务状态只存内存（自用定位，重启即失），不引入数据库。
"""

import asyncio
import logging
import math
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
from .translation_worker import install

install()

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
    codex_cancel_file: Path | None = None
    stage_seconds: dict[str, float] = field(default_factory=dict)
    stage_current: int | None = None
    stage_total: int | None = None
    updated_at: float = field(default_factory=time.time)
    preview_pages: int = 0
    preview_total: int | None = None
    untranslated_pages: list[int] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "stage": self.stage,
            "stage_current": self.stage_current,
            "stage_total": self.stage_total,
            "updated_at": self.updated_at,
            "overall_progress": round(self.overall_progress, 1),
            "error": self.error,
            "has_mono": self.mono_path is not None,
            "has_dual": self.dual_path is not None,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "preview_pages": self.preview_pages,
            "preview_total": self.preview_total,
            "untranslated_pages": list(self.untranslated_pages),
            "stage_seconds": {key: round(value, 3) for key, value in self.stage_seconds.items()},
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
        self._local_sem = asyncio.Semaphore(1)
        self._codex_sem = asyncio.Semaphore(1)
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
        if engine.type == "codex":
            task.codex_cancel_file = self._codex_cancel_path(task.id)
        settings.validate_settings()
        task.job = asyncio.create_task(
            self._run(task, settings, pdf_path, engine.type == "ollama", engine.type == "codex")
        )
        self.tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task is None or task.status != "running" or task.job is None:
            return False
        if task.job.cancelling():
            return True
        if task.codex_cancel_file:
            task.codex_cancel_file.parent.mkdir(parents=True, exist_ok=True)
            task.codex_cancel_file.touch()
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
                qps=8 if engine.type == "codex" else (2 if engine.type == "ollama" else 20),
                pool_max_workers=8 if engine.type == "codex" else None,
                no_auto_extract_glossary=True,
            ),
            pdf=PDFSettings(
                pages=pages,
                watermark_output_mode="no_watermark",
            ),
            translate_engine_settings=build_engine_settings(
                engine, lang_in, lang_out,
                self._codex_cancel_path(task_id) if engine.type == "codex" else None,
            ),
        )

    @staticmethod
    def _codex_cancel_path(task_id: str) -> Path:
        return Path(__file__).resolve().parents[2] / ".tmp/codex/tasks" / task_id / "cancel"

    async def _run(
        self,
        task: Task,
        settings: SettingsModel,
        pdf_path: Path,
        is_local: bool,
        is_codex: bool = False,
    ) -> None:
        try:
            task.stage = "排队中"  # 等待并发闸期间前端展示
            if is_codex:
                async with self._codex_sem:
                    async with self._sem:
                        await self._translate(task, settings, pdf_path)
            elif is_local:
                # 本地模型单任务运行，排队时不占用云端任务的全局并发槽。
                async with self._local_sem:
                    async with self._sem:
                        await self._translate(task, settings, pdf_path)
            else:
                async with self._sem:
                    await self._translate(task, settings, pdf_path)
        except asyncio.CancelledError:
            task.status = "cancelled"
        except Exception as exc:  # 管线内部异常统一转任务错误，不让服务崩
            task.status = "error"
            task.error = str(exc)
        finally:
            if task.codex_cancel_file and task.status != "done":
                task.codex_cancel_file.parent.mkdir(parents=True, exist_ok=True)
                task.codex_cancel_file.touch()
            if task.status == "running":
                task.status = "error"
                task.error = "translation ended without finish event"
            task.finished_at = time.time()
            task.updated_at = task.finished_at
            # 源文件翻译后已无用，立即清理；输出目录保留供下载，交给 GC
            _safe_rmtree(task.upload_dir)

    async def _translate(
        self, task: Task, settings: SettingsModel, pdf_path: Path
    ) -> None:
        stage_started: dict[str, float] = {}
        async for event in do_translate_async_stream(settings, pdf_path):
            task.updated_at = time.time()
            etype = event.get("type")
            stage = event.get("stage")
            if etype == "progress_start" and stage:
                stage_started.setdefault(stage, time.perf_counter())
                logger.info("task=%s stage=%s started", task.id, stage)
            elif etype == "progress_end" and stage in stage_started:
                seconds = time.perf_counter() - stage_started.pop(stage)
                task.stage_seconds[stage] = task.stage_seconds.get(stage, 0) + seconds
                logger.info("task=%s stage=%s finished seconds=%.3f", task.id, stage, seconds)
            if etype in {"progress_start", "progress_update", "progress_end"}:
                if stage != task.stage or etype == "progress_start":
                    task.stage_current = task.stage_total = None
                task.stage = event.get("stage") or task.stage
                for key in ("stage_current", "stage_total"):
                    value = event.get(key)
                    if isinstance(value, int) and value >= 0:
                        setattr(task, key, value)
                progress = event.get("overall_progress")
                if isinstance(progress, (int, float)) and math.isfinite(progress):
                    # 上游重复阶段可能回退；100% 留给后处理完成。
                    task.overall_progress = max(task.overall_progress, min(99.0, progress))
            elif etype == "preview_ready":
                page = event.get("page_number")
                if isinstance(page, int) and page == task.preview_pages + 1:
                    preview = self.output_root / task.id / "preview" / f"{page}.png"
                    if preview.is_file():
                        task.preview_pages = page
                        task.preview_total = event.get("total_pages")
                        if event.get("untranslated"):
                            task.untranslated_pages.append(page)
            elif etype == "error":
                task.status = "error"
                task.error = str(event.get("error"))
                break
            elif etype == "finish":
                result = event["translate_result"]
                mono = getattr(result, "mono_pdf_path", None)
                dual = getattr(result, "dual_pdf_path", None)
                mono_path = Path(mono) if mono else None
                dual_path = Path(dual) if dual else None
                task.stage = "PDF 后处理"
                task.stage_current = task.stage_total = None
                # 后处理：清除上游遗留的控制字符
                cleaning = asyncio.create_task(asyncio.to_thread(clean_outputs, mono_path, dual_path))
                try:
                    await asyncio.shield(cleaning)
                except asyncio.CancelledError:
                    # 线程无法中途停止，等文件操作完成再释放任务和并发槽。
                    await cleaning
                    raise
                task.mono_path, task.dual_path = mono_path, dual_path
                task.overall_progress = 100.0
                task.updated_at = time.time()
                task.status = "done"
                break

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
