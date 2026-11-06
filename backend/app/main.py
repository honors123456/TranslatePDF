"""TranslationPDF 后端：上传 + 翻译任务 + SSE 进度 + 下载。"""

import asyncio
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from .engines import EngineConfig, test_connection
from .model_catalog import list_models
from .tasks import TaskManager

for logger_name in ("app.tasks", "app.gpu_patch", "app.section_translator", "pdf2zh_next.high_level"):
    stage_logger = logging.getLogger(logger_name)
    if not stage_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        stage_logger.addHandler(handler)
    stage_logger.setLevel(logging.INFO)
    stage_logger.propagate = False

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"
UPLOAD_DIR = DATA_ROOT / "uploads"
OUTPUT_DIR = DATA_ROOT / "outputs"

manager = TaskManager(output_root=OUTPUT_DIR, upload_root=UPLOAD_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.startup_cleanup()  # 清空遗留孤儿目录
    manager.start_gc()  # 后台定时回收超期任务
    yield
    manager.stop_gc()


app = FastAPI(title="TranslationPDF", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/test-connection")
async def test_engine_connection(engine: EngineConfig):
    try:
        return await test_connection(engine)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # 网络错误等
        return {"ok": False, "detail": str(exc)}


@app.post("/api/models")
async def engine_models(engine: EngineConfig):
    try:
        async with asyncio.timeout(45):
            return {"models": await list_models(engine)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "模型目录刷新失败，请检查网络、服务地址与登录状态。") from exc


@app.post("/api/tasks")
async def create_task(
    file: UploadFile,
    engine: str = Form(...),  # EngineConfig 的 JSON 字符串
    lang_in: str = Form("en"),
    lang_out: str = Form("zh"),
    pages: str | None = Form(None),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "only PDF files are supported")
    try:
        engine_config = EngineConfig.model_validate(json.loads(engine))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(400, f"invalid engine config: {exc}") from exc

    # 落盘上传文件：目录用随机 id 隔离，文件名只保留安全字符
    upload_id = uuid.uuid4().hex[:12]
    safe_name = re.sub(r"[^\w.\-一-鿿]", "_", Path(file.filename).name)
    pdf_path = UPLOAD_DIR / upload_id / safe_name
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with pdf_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)

    try:
        task = manager.create(pdf_path, engine_config, lang_in, lang_out, pages)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return task.snapshot()


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return task.snapshot()


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str):
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")

    async def event_stream():
        # 轮询快照推送：实现简单且断线重连天然安全，自用场景足够
        last_payload = None
        idle_ticks = 0
        while True:
            snapshot = task.snapshot()
            payload = json.dumps(snapshot, ensure_ascii=False)
            if payload != last_payload:
                last_payload = payload
                idle_ticks = 0
                yield f"data: {payload}\n\n"
            else:
                idle_ticks += 1
                if idle_ticks >= 30:
                    idle_ticks = 0
                    yield ": heartbeat\n\n"
            # 以本次发送的快照判断结束，避免 yield 期间完成而漏发最终状态。
            if snapshot["status"] != "running":
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/tasks/{task_id}/download")
async def download(task_id: str, kind: str = "dual", inline: bool = False):
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    if kind not in ("dual", "mono"):
        raise HTTPException(400, "kind must be dual or mono")
    path = {"dual": task.dual_path, "mono": task.mono_path}[kind]
    if path is None or not path.exists():
        raise HTTPException(404, f"{kind} output not available")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline" if inline else "attachment",
    )


@app.get("/api/tasks/{task_id}/preview/{page_number}")
async def preview_page(task_id: str, page_number: int):
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    if page_number < 1 or page_number > task.preview_pages:
        raise HTTPException(404, "preview page not ready")
    path = OUTPUT_DIR / task.id / "preview" / f"{page_number}.png"
    if not path.is_file():
        raise HTTPException(404, "preview page not available")
    return FileResponse(path, media_type="image/png")


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    manager.cancel(task_id)
    return task.snapshot()
