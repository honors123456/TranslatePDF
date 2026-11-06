"""在项目内适配 BabelDOC 的段落排版接口，不修改第三方安装文件。"""

import json
import logging
import re
import time
import subprocess
import uuid

from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator

from . import codex_batch

logger = logging.getLogger(__name__)
MAX_CHARS = 12000
MAX_PARAGRAPHS = 24


def failure_reason(exc):
    # 不记录异常全文、stderr 或正文；RetryError 展开后仅保留类型及受控原因。
    attempt = getattr(exc, "last_attempt", None)
    if attempt is not None:
        exc = attempt.exception() or exc
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return "request_timeout", type(exc).__name__
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        for marker, category in (("Codex 翻译请求超时", "request_timeout"),
                                 ("usage_limit_reached", "quota_exhausted"),
                                 ("insufficient_quota", "quota_exhausted"),
                                 ("rate_limit_exceeded", "rate_limited"),
                                 ("context_length_exceeded", "context_too_long"),
                                 ("HTTP 401", "authentication_failed")):
            if marker in stderr:
                return category, type(exc).__name__
        return f"cli_exit_{exc.returncode}", type(exc).__name__
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json", type(exc).__name__
    if isinstance(exc, ValueError):
        known = {"batch result count mismatch", "invalid batch row", "invalid batch id or text",
                 "batch id mismatch", "batch placeholder mismatch",
                 "batch introduced or removed formula placeholder"}
        return (str(exc) if str(exc) in known else "validation_error"), type(exc).__name__
    return "request_error", type(exc).__name__


class SectionTranslator(ILTranslator):
    def translate(self, docs):
        self._pending = []
        self._pending_chars = 0
        self._last_page = docs.page[-1] if docs.page else None
        try:
            return super().translate(docs)
        finally:
            self._pending.clear()

    def process_page(self, page, executor, pbar=None, tracker=None):
        owner = self

        class Collector:
            def submit(self, function, *args, **kwargs):
                kwargs.pop("priority", None)
                paragraph = args[0]
                size = len(paragraph.unicode or "")
                if owner._pending and (
                    paragraph.layout_label == "title"
                    or owner._pending_chars + size > MAX_CHARS
                    or len(owner._pending) >= MAX_PARAGRAPHS
                ):
                    owner._flush(executor)
                owner._pending.append((args, kwargs))
                owner._pending_chars += size

        # 复用上游字体映射、标题上下文及 tracker 的构造。
        super().process_page(page, Collector(), pbar, tracker)
        if page is self._last_page:
            self._flush(executor)

    def _flush(self, executor):
        if self._pending:
            executor.submit(self._translate_section, self._pending, priority=0)
            self._pending = []
            self._pending_chars = 0

    def _translate_section(self, entries):
        prepared = []
        for args, kwargs in entries:
            self.translation_config.raise_if_cancelled()
            paragraph, page, pbar, tracker, font_map, xobj_map = args
            try:
                text, translation_input = self.pre_translate_paragraph(
                    paragraph, tracker, font_map, xobj_map
                )
            except Exception:
                # 保留上游对特殊段落的错误处理及进度行为。
                super().translate_paragraph(*args, **kwargs)
                continue
            if text is None:
                if pbar:
                    pbar.advance(1)
                continue
            tokens = []
            for placeholder in translation_input.placeholders:
                for key in ("placeholder", "left_placeholder", "right_placeholder"):
                    token = getattr(placeholder, key, None)
                    if token:
                        tokens.append(token)
            tokens.extend(getattr(translation_input, "original_placeholder_tokens", {}))
            prepared.append((args, translation_input, text, list(set(tokens))))
        if not prepared:
            return
        texts = [entry[2] for entry in prepared]
        placeholders = [entry[3] for entry in prepared]
        results = self._request(texts, placeholders)
        for (args, translation_input, text, tokens), result in zip(prepared, results, strict=True):
            self.translation_config.raise_if_cancelled()
            paragraph, page, pbar, tracker, _, _ = args
            try:
                if result is not None:
                    self.post_translate_paragraph(
                        paragraph, tracker, translation_input,
                        re.sub(r"[. 。…，]{20,}", ".", result),
                    )
            except Exception:
                logger.warning("section paragraph writeback failed", exc_info=True)
            finally:
                if pbar:
                    pbar.advance(1)

    def _request(self, texts, placeholders):
        self.translation_config.raise_if_cancelled()
        started = time.perf_counter()
        request_id = uuid.uuid4().hex[:8]
        logger.info("section request_start id=%s paragraphs=%s chars=%s",
                    request_id, len(texts), sum(map(len, texts)))
        try:
            if len(texts) == 1:
                result = self.translate_engine.translate(texts[0])
                # 单段回退也必须保留占位符。
                codex_batch.decode(
                    json.dumps([{"id": "0", "text": result}]), texts, placeholders
                )
                return [result]
            output = self.translate_engine.translate(codex_batch.encode(texts))
            return codex_batch.decode(output, texts, placeholders)
        except Exception as exc:
            self.translation_config.raise_if_cancelled()
            reason, error_type = failure_reason(exc)
            logger.warning("section failure id=%s paragraphs=%s chars=%s seconds=%.3f reason=%s error_type=%s",
                           request_id, len(texts), sum(map(len, texts)), time.perf_counter() - started,
                           reason, error_type)
            if len(texts) == 1:
                logger.warning("section single paragraph translation failed; preserving source")
                return [None]
            logger.warning("section batch invalid; splitting paragraphs=%s", len(texts))
            middle = len(texts) // 2
            return (self._request(texts[:middle], placeholders[:middle])
                    + self._request(texts[middle:], placeholders[middle:]))
        finally:
            logger.info("section request id=%s paragraphs=%s chars=%s seconds=%.3f",
                        request_id, len(texts), sum(map(len, texts)), time.perf_counter() - started)


def install(settings):
    engine = getattr(settings, "translate_engine_settings", None)
    command = getattr(engine, "clitranslator_command", "")
    if "codex_cli.py" in command:
        from babeldoc.format.pdf import high_level

        high_level.ILTranslator = SectionTranslator
