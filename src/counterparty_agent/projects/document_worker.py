"""Изолированный парсер документов; вызывается только локальным API."""

import json
import sys


def main() -> None:
    # Лимиты устанавливаются до импорта парсеров. Ошибка установки — безопасный отказ.
    import resource

    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    from fastapi import HTTPException

    from counterparty_agent.projects.documents import (
        MAX_DOCUMENT_BYTES,
        _extract_document_in_worker,
    )

    try:
        content = sys.stdin.buffer.read(MAX_DOCUMENT_BYTES + 1)
        document = _extract_document_in_worker(sys.argv[1], content)
        sys.stdout.write(document.model_dump_json())
    except HTTPException as error:
        sys.stdout.write(json.dumps({"error": error.detail}, ensure_ascii=False))


if __name__ == "__main__":
    main()
