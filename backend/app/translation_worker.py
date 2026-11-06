"""在 pdf2zh-next 的 Windows spawn 翻译入口初始化项目的 GPU 配置。"""

import logging
from logging.handlers import QueueHandler

from pdf2zh_next import high_level

from . import gpu_patch
from . import section_translator
from . import pipeline_diagnostics
from . import toc_layout
from . import page_preview

_original_worker = high_level._translate_wrapper


def gpu_translation_worker(settings, file, progress_pipe, cancel_pipe, logger_queue):
    logging.basicConfig(level=logging.INFO, handlers=[QueueHandler(logger_queue)])
    gpu_patch.apply()
    toc_layout.install()
    section_translator.install(settings)
    page_preview.install(settings)
    return _original_worker(settings, file, progress_pipe, cancel_pipe, logger_queue)


def install() -> None:
    pipeline_diagnostics.install()
    # 保留上游的进度、取消与异常处理，仅替换可被 spawn 导入的初始化入口。
    high_level._translate_wrapper = gpu_translation_worker
