"""Безопасное извлечение текста пользовательского документа; инструкции не выполняются."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from pathlib import Path, PurePath
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException

from counterparty_agent.projects.models import DocumentFragment, ProjectDocument

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_TEXT = 60_000
ALLOWED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


def extract_document(name: str, content: bytes) -> ProjectDocument:
    """Изолировать парсер от API-процесса; в окружении дочернего процесса нет секретов."""
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(422, "Размер документа должен быть от 1 байта до 2 МБ.")
    suffix = PurePath(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(422, "Поддерживаются TXT, Markdown, PDF и DOCX.")
    import psutil  # type: ignore[import-untyped]

    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "counterparty_agent.projects.document_worker", name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **{key: value for key, value in os.environ.items() if key in {"PATH", "LANG"}},
                "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            },
        )
        monitor = psutil.Process(process.pid)
        started = time.monotonic()
        # Один communicate передаёт весь stdin. Повтор с input=None после таймаута
        # может оставить длинный ввод недописанным и навсегда ждать EOF в парсере.
        with ThreadPoolExecutor(max_workers=1) as pool:
            exchange = pool.submit(process.communicate, content, timeout=8)
            try:
                while True:
                    try:
                        output, _ = exchange.result(timeout=0.05)
                        break
                    except FutureTimeout:
                        try:
                            too_large = monitor.memory_info().rss > 512 * 1024 * 1024
                        except psutil.NoSuchProcess:
                            too_large = False
                        if time.monotonic() - started > 8 or too_large:
                            raise HTTPException(
                                422, "Документ превышает лимит времени или памяти."
                            ) from None
            finally:
                if process.poll() is None:
                    process.kill()
    except (subprocess.TimeoutExpired, OSError, psutil.Error):
        raise HTTPException(
            422, "Извлечение текста превысило лимит. Загрузите меньший фрагмент."
        ) from None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
    if process.returncode != 0:
        raise HTTPException(422, "Документ повреждён или превышает лимиты обработки.")
    try:
        value = json.loads(output)
        if "error" in value:
            raise HTTPException(422, value["error"])
        return ProjectDocument.model_validate(value)
    except (ValueError, TypeError):
        raise HTTPException(422, "Не удалось прочитать документ.") from None


def _extract_document_in_worker(name: str, content: bytes) -> ProjectDocument:
    """Храним только текстовые фрагменты, не исходный файл и не исполняемый контент."""

    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(422, "Размер документа должен быть от 1 байта до 2 МБ.")
    clean_name = PurePath(name.replace("\\", "/")).name[:120]
    suffix = PurePath(clean_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(422, "Поддерживаются TXT, Markdown, PDF и DOCX.")
    try:
        parts = _extract_parts(suffix, content)
    except HTTPException:
        raise
    except (ValueError, UnicodeError, BadZipFile, KeyError, OSError):
        raise HTTPException(422, "Не удалось прочитать документ. Проверьте формат файла.") from None
    if sum(len(text) for _, text in parts) > MAX_DOCUMENT_TEXT:
        raise HTTPException(
            422, "В документе слишком много текста. Загрузите нужный раздел отдельно."
        )
    document_id = f"doc_{secrets.token_hex(12)}"
    digest = hashlib.sha256(content).hexdigest()
    fragments = []
    for location, text in parts:
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text).strip()
        for offset in range(0, len(text), 1200):
            snippet = text[offset : offset + 1200]
            key = hashlib.sha256(
                f"{document_id}:{digest}:{location}:{offset}".encode()
            ).hexdigest()[:24]
            fragments.append(
                DocumentFragment(
                    evidence_id=f"doc_evidence_{key}",
                    text=snippet,
                    location=f"{location}, фрагмент {offset // 1200 + 1}",
                )
            )
    return ProjectDocument(
        document_id=document_id,
        name=clean_name,
        content_hash=digest,
        uploaded_at=datetime.now(UTC),
        fragments=fragments,
        status="ready" if fragments else "no_text",
        note="Пользовательский документ. Сведения не подтверждены банковским отчётом."
        if fragments
        else "Текст не найден. Для скана нужен документ с текстовым слоем; OCR не подключён.",
    )


def _extract_parts(suffix: str, content: bytes) -> list[tuple[str, str]]:
    if suffix in {".txt", ".md"}:
        return [("Текст", content.decode("utf-8-sig"))]
    if suffix == ".pdf":
        from pypdf import PdfReader

        if not content.startswith(b"%PDF-"):
            raise HTTPException(422, "Содержимое не соответствует PDF.")
        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted or len(reader.pages) > 30:
                raise HTTPException(422, "Нужен PDF без пароля, не более 30 страниц.")
            return [
                (f"Страница {i + 1}", page.extract_text() or "")
                for i, page in enumerate(reader.pages)
            ]
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "PDF повреждён или не поддерживается.") from None
    from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]

    with ZipFile(io.BytesIO(content)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 10 * 1024 * 1024:
            raise HTTPException(422, "Распакованный DOCX превышает допустимый размер.")
        if len(archive.infolist()) > 1000:
            raise HTTPException(422, "Слишком сложный DOCX. Загрузите текстовый фрагмент.")
        try:
            root = fromstring(archive.read("word/document.xml"))
        except Exception:
            raise HTTPException(
                422, "DOCX повреждён или содержит недопустимую XML-структуру."
            ) from None
        paragraphs = root.findall(
            ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
        )
        return [(f"Абзац {i + 1}", "".join(node.itertext())) for i, node in enumerate(paragraphs)]
