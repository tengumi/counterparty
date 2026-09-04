# Проверки

`uv run ruff check .`, `uv run mypy`, `uv run pytest`.
Frontend: `cd frontend`, затем `pnpm test` и `pnpm build`.

- `test_sources`, `test_query_resolution`: данные, ID, exact/fuzzy и aliases.
- `test_analysis`, `test_comparison`: числа, пропуски, периоды, lineage.
- `test_llm`: строгий выбор фактов, repair и безопасные отказы без сети.
- `test_graph`, `test_app`: маршруты, сессии, группы, owner/TTL и HTTP.
- `test_projects`, `test_project_dialogue`: версии, файлы, memo, scope и периоды.
- `test_synthetic_benchmark`: независимые ожидаемые значения и N до 100.
- `test_scaffold`: прямые импорты, установленные команды запуска, отсутствие
  файлов-переэкспортов и готовая сборка UI.
- `frontend/src/workspace/contracts.test.ts`: точность представления,
  фильтры/различия, страницы таблицы и принадлежность источников.

Основной regression-набор использует локальный выданный JSON; тесты его не
изменяют. Если файла нет, соответствующие проверки явно пропускаются.
Синтетические тесты полностью воспроизводимы и работают без рабочего источника.
Подменённый LLM-транспорт не является оценкой реального качества модели.
TODO: экспертный набор релевантности и нагрузочный прогон конкурентных проектов.
