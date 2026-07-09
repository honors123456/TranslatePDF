"""让 babeldoc 版面分析（DocLayout-YOLO）使用 GPU。

上游 babeldoc 出于兼容性考虑在非 macOS 上强制 CPU provider
（见 babeldoc/docvision/doclayout.py），本机 RTX 3050 + DirectML
实测正常，版面分析 0.89s/页 → 0.11s/页（约 8 倍）。

依赖 onnxruntime-directml（替代 onnxruntime 安装）；若该包不在或无
GPU provider，本补丁不生效，自动保持上游 CPU 行为。回退方式：
pip uninstall onnxruntime-directml && pip install onnxruntime
"""

import logging
from types import SimpleNamespace

import onnxruntime

import babeldoc.docvision.doclayout as doclayout

logger = logging.getLogger(__name__)

_PREFERRED_GPU = ["DmlExecutionProvider", "CUDAExecutionProvider"]


def apply() -> None:
    available = onnxruntime.get_available_providers()
    gpu = [p for p in _PREFERRED_GPU if p in available]
    if not gpu:
        logger.info("no GPU onnxruntime provider available, doclayout stays on CPU")
        return

    providers = [*gpu, "CPUExecutionProvider"]

    def patched_session(model_bytes, *args, **kwargs):
        kwargs.pop("providers", None)
        return onnxruntime.InferenceSession(
            model_bytes, *args, providers=providers, **kwargs
        )

    # 只替换 doclayout 模块看到的 onnxruntime 引用，不污染全局模块
    doclayout.onnxruntime = SimpleNamespace(
        InferenceSession=patched_session,
        get_available_providers=onnxruntime.get_available_providers,
    )
    logger.info("doclayout GPU providers enabled: %s", gpu)
