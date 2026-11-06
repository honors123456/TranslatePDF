"""CPU/DirectML 子进程版面识别对比；不调用翻译服务，不修改源 PDF。"""

import argparse
import asyncio
import json
import multiprocessing
import queue
import statistics
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def measure(settings, source, result_queue, cancel_pipe, logger_queue):
    import numpy as np
    import onnxruntime as ort
    import pymupdf
    from babeldoc.docvision.doclayout import OnnxModel
    from babeldoc.format.pdf.document_il.utils.mupdf_helper import get_no_rotation_img

    original = ort.InferenceSession
    def profiled_session(model, *args, **kwargs):
        options = kwargs.get("sess_options") or ort.SessionOptions()
        options.enable_profiling = True
        options.profile_file_prefix = str(ROOT / ".tmp/gpu-benchmark/profile")
        kwargs["sess_options"] = options
        return original(model, *args, **kwargs)
    ort.InferenceSession = profiled_session
    started = time.perf_counter()
    model = OnnxModel.from_pretrained()
    initialization = time.perf_counter() - started
    ort.InferenceSession = original
    render_seconds = 0.0
    images = []
    with pymupdf.open(source) as document:
        for page in range(min(settings, len(document))):
            started = time.perf_counter()
            pix = get_no_rotation_img(document[page])
            images.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)[:, :, ::-1])
            render_seconds += time.perf_counter() - started
    started = time.perf_counter()
    model.predict(images[0])
    warmup = time.perf_counter() - started
    elapsed = []
    boxes = []
    for repeat in range(3):
        for image in images:
            started = time.perf_counter()
            prediction = model.predict(image)[0]
            elapsed.append(time.perf_counter() - started)
            if repeat == 0:
                boxes.append([[*box.xyxy.tolist(), float(box.conf), int(box.cls)] for box in prediction.boxes])
    profile = json.loads(Path(model.model.end_profiling()).read_text(encoding="utf-8"))
    providers = {}
    for event in profile:
        provider = event.get("args", {}).get("provider")
        if provider:
            providers[provider] = providers.get(provider, 0) + 1
    result_queue.put({"providers": model.model.get_providers(), "profile_nodes": providers,
        "initialization_seconds": initialization, "warmup_seconds": warmup,
        "render_seconds": render_seconds, "mean_page_seconds": statistics.mean(elapsed),
        "median_page_seconds": statistics.median(elapsed), "samples": len(elapsed), "boxes": boxes})


def worker(mode, source, pages, results, logs):
    if mode == "gpu":
        from app import translation_worker
        translation_worker._original_worker = measure
        translation_worker.install()
        from pdf2zh_next import high_level
        high_level._translate_wrapper(pages, source, results, None, logs)
    else:
        measure(pages, source, results, None, logs)


def compare_boxes(cpu, gpu):
    maximum_coordinate_error = maximum_confidence_error = 0.0
    for expected, actual in zip(cpu, gpu, strict=True):
        remaining = list(actual)
        for box in expected:
            candidates = [other for other in remaining if other[-1] == box[-1]]
            if not candidates:
                raise RuntimeError("GPU layout classes differ from CPU")
            match = min(candidates, key=lambda other: max(abs(a - b) for a, b in zip(box[:4], other[:4])))
            remaining.remove(match)
            maximum_coordinate_error = max(maximum_coordinate_error, max(abs(a - b) for a, b in zip(box[:4], match[:4])))
            maximum_confidence_error = max(maximum_confidence_error, abs(box[4] - match[4]))
        if remaining:
            raise RuntimeError("GPU has additional layout boxes")
    if maximum_coordinate_error > 1:
        raise RuntimeError(f"GPU layout changed by more than one pixel: {maximum_coordinate_error}")
    return {"max_coordinate_error_pixels": maximum_coordinate_error, "max_confidence_error": maximum_confidence_error}


async def pipeline(mode, source, pages):
    from app import translation_worker
    from app.tasks import Task, TaskManager
    from pdf2zh_next import high_level
    from pdf2zh_next.config.model import PDFSettings, SettingsModel, TranslationSettings
    from pdf2zh_next.config.translate_engine_model import CLISettings

    if mode == "cpu":
        high_level._translate_wrapper = translation_worker._original_worker
    else:
        translation_worker.install()
    output = ROOT / ".tmp/gpu-benchmark/pipeline" / mode
    settings = SettingsModel(
        translation=TranslationSettings(output=str(output), lang_in="en", lang_out="zh", qps=1,
                                        pool_max_workers=1, no_auto_extract_glossary=True, ignore_cache=True),
        pdf=PDFSettings(pages=f"1-{pages}", watermark_output_mode="no_watermark"),
        translate_engine_settings=CLISettings(clitranslator_command=shlex.join(
            [sys.executable, str(Path(__file__).resolve()), "--echo"])),
    )
    settings.validate_settings()
    task = Task(mode, source.name)
    manager = TaskManager(output, output / "unused-upload")
    started = time.perf_counter()
    await manager._translate(task, settings, source)
    if task.status != "done" or not task.mono_path.is_file() or not task.dual_path.is_file():
        raise RuntimeError(f"pipeline failed: {task.error}")
    return {"total_seconds": time.perf_counter() - started, "stage_seconds": task.snapshot()["stage_seconds"],
            "mono": str(task.mono_path), "dual": str(task.dual_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="?", type=Path, default=ROOT / "data/samples/attention.pdf")
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--pipeline", action="store_true", help="also verify full pipeline with local identity translation")
    args = parser.parse_args()
    if args.pages < 1 or not args.pdf.is_file():
        parser.error("PDF must exist and pages must be positive")
    output = ROOT / ".tmp/gpu-benchmark"
    output.mkdir(parents=True, exist_ok=True)
    context = multiprocessing.get_context("spawn")
    comparison = {}
    for mode in ("cpu", "gpu"):
        results, logs = context.Queue(), context.Queue()
        process = context.Process(target=worker, args=(mode, args.pdf, args.pages, results, logs))
        process.start()
        try:
            deadline = time.monotonic() + 300
            while True:
                try:
                    result = results.get(timeout=1)
                    break
                except queue.Empty:
                    if not process.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError(f"benchmark child failed or timed out: {process.exitcode}")
            process.join(timeout=10)
            if process.is_alive():
                raise RuntimeError("benchmark child did not exit")
        finally:
            if process.is_alive():
                process.terminate()
                process.join()
            results.close()
            logs.close()
        if process.exitcode:
            raise RuntimeError(f"benchmark child exit={process.exitcode}")
        comparison[mode] = result
        print(json.dumps({mode: {k: v for k, v in result.items() if k != "boxes"}}), flush=True)
    comparison["speedup"] = comparison["cpu"]["mean_page_seconds"] / comparison["gpu"]["mean_page_seconds"]
    comparison["same_box_counts"] = [len(b) for b in comparison["cpu"]["boxes"]] == [len(b) for b in comparison["gpu"]["boxes"]]
    comparison["box_comparison"] = compare_boxes(comparison["cpu"]["boxes"], comparison["gpu"]["boxes"])
    if "DmlExecutionProvider" not in comparison["gpu"]["profile_nodes"]:
        raise RuntimeError("No DirectML inference nodes were observed")
    if args.pipeline:
        comparison["pipeline"] = {}
        for mode in ("cpu", "gpu"):
            comparison["pipeline"][mode] = asyncio.run(pipeline(mode, args.pdf, args.pages))
            print(json.dumps({"pipeline": mode, **comparison["pipeline"][mode]}), flush=True)
    (output / "results.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    print(json.dumps({"speedup": comparison["speedup"], "same_box_counts": comparison["same_box_counts"]}))


if __name__ == "__main__":
    if sys.argv[1:] == ["--echo"]:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        print(sys.stdin.read(), end="")
    else:
        main()
