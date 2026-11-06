"""让 babeldoc 版面分析（DocLayout-YOLO）使用 GPU。

在实际翻译子进程中调用 apply；仅发现 GPU provider 不代表模型已在 GPU 执行。

依赖 onnxruntime-directml（替代 onnxruntime 安装）；若该包不在或无
GPU provider，本补丁不生效，自动保持上游 CPU 行为。回退方式：
pip uninstall onnxruntime-directml && pip install onnxruntime
"""

import logging
import os
import threading
from types import SimpleNamespace

import onnxruntime

import babeldoc.docvision.doclayout as doclayout

logger = logging.getLogger(__name__)

_PREFERRED_GPU = ["DmlExecutionProvider", "CUDAExecutionProvider"]


class _SequentialSession:
    def __init__(self, session):
        self._session = session
        self._lock = threading.Lock()

    def run(self, *args, **kwargs):
        with self._lock:
            return self._session.run(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


def apply() -> None:
    available = onnxruntime.get_available_providers()
    gpu = [p for p in _PREFERRED_GPU if p in available]
    if not gpu:
        logger.info("no GPU onnxruntime provider available, doclayout stays on CPU")
        return

    providers = [*gpu, "CPUExecutionProvider"]

    def patched_session(model_bytes, *args, **kwargs):
        kwargs.pop("providers", None)
        if args:
            options = args[0] or onnxruntime.SessionOptions()
            args = (options, *args[1:])
        else:
            options = kwargs.get("sess_options") or onnxruntime.SessionOptions()
            kwargs["sess_options"] = options
        if "DmlExecutionProvider" in gpu:
            options.enable_mem_pattern = False
            options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
        try:
            session = onnxruntime.InferenceSession(
                model_bytes, *args, providers=providers, **kwargs
            )
        except Exception as exc:
            logger.warning("layout GPU initialization failed; retry CPU: %s", exc)
            session = onnxruntime.InferenceSession(
                model_bytes, *args, providers=["CPUExecutionProvider"], **kwargs
            )
        logger.info("layout session pid=%s requested=%s actual=%s", os.getpid(), providers, session.get_providers())
        return _SequentialSession(session) if "DmlExecutionProvider" in session.get_providers() else session

    # 只替换 doclayout 模块看到的 onnxruntime 引用，不污染全局模块
    doclayout.onnxruntime = SimpleNamespace(
        InferenceSession=patched_session,
        get_available_providers=onnxruntime.get_available_providers,
    )
    logger.info("doclayout GPU providers enabled: %s", gpu)
