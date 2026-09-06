# WEB-07 — результат browser QA

**Pass with limitations** по независимой проверке H3; открытых WEB-07 blockers нет. Проверены 390×844, 1024×768 и 1440×900: S1/S2, материалы, отчёт, evidence, loading/error/empty, keyboard/focus, сохранение draft/scroll. Отдельный live REST flow создал и переименовал проект, добавил две компании с частичным not_found, удалил одну и проверил reload.

| Прогон | Source SHA | Checks | PNG |
|---|---|---:|---:|
| [Первый полный](manifest-all.json) | `b13cc17` | 90 pass, 4 исправлены ниже | 27 |
| [Tablet S2 после исправления](follow-up/manifest-tablet-s2.json) | `6942d5a` | 26/26 pass | 4 |
| [Availability + mobile после исправления](follow-up/manifest-availability.json) | `6942d5a` | 13/13 pass | 3 |

Первый прогон обнаружил схлопывание tablet-панели до 1 px; H1 исправил её containing block. Ещё два failure были ошибкой harness: selector находил скрытый дубликат текста в другом разделе. Section-scoped проверки прошли. H3 также выявил неуместную подсказку desktop Enter на mobile; новый mobile S2 отражает исправление. Во всех прогонах `consoleErrors=[]`.

[Машинный индекс](index.json) связывает исправленные результаты и replacement PNG. **Старые PNG сохраняют SHA своего первого прогона:** они не выданы за снимки нового исходника.

## Ключевые экраны

| Размер | S1 | S2 | Материалы | Отчёт / evidence |
|---|---|---|---|---|
| 1440×900 | [S1](typed-fixtures/desktop/s1-populated.png) | [S2](typed-fixtures/desktop/s2-conversation.png) | [P1](typed-fixtures/desktop/materials.png) | [Отчёт](typed-fixtures/desktop/report.png) · [Evidence](typed-fixtures/desktop/evidence.png) |
| 1024×768 | [S1](typed-fixtures/tablet/s1-populated.png) | [S2](follow-up/typed-fixtures/tablet/s2-conversation.png) | [P1 исправлен](follow-up/typed-fixtures/tablet/materials.png) | [Отчёт](follow-up/typed-fixtures/tablet/report.png) · [Evidence](follow-up/typed-fixtures/tablet/evidence.png) |
| 390×844 | [S1](typed-fixtures/mobile/s1-populated.png) | [S2 исправлен](follow-up/typed-fixtures/mobile/s2-conversation.png) | [P1](typed-fixtures/mobile/materials.png) | [Отчёт](typed-fixtures/mobile/report.png) · [Evidence](typed-fixtures/mobile/evidence.png) |

Дополнительно: [empty](typed-fixtures/desktop/s1-empty.png), [loading](typed-fixtures/desktop/s1-loading.png), [error](typed-fixtures/desktop/s1-error.png), [длинное название](typed-fixtures/mobile/long-name.png), [переключатель чата](typed-fixtures/mobile/chat-switcher.png), [live CRUD после reload](live-rest/desktop/crud-reloaded.png).

Неизменённый reference: [desktop S1](design-reference/desktop/s1-populated.png) / [S2](design-reference/desktop/s2-conversation.png), [tablet S1](design-reference/tablet/s1-populated.png) / [S2](design-reference/tablet/s2-conversation.png), [mobile S1](design-reference/mobile/s1-populated.png) / [S2](design-reference/mobile/s2-conversation.png). Hash HTML и support.js сохранены в каждом manifest.

## Воспроизведение и границы

[QA runbook](../../../apps/web/qa/README.md): Node 24.19.0, Chrome 150.0.7871.115, Playwright Core 1.63.0; отдельный временный profile, стандартный CDP. `lint`, `typecheck`, `qa:check`, 77 unit tests и production build прошли; остаётся warning размера JS bundle.

Typed fixtures проверяют интерфейс WEB-07, не закрывают WEB-08/09. У reference нет полноценного адаптивного shell, поэтому на узких экранах применены требования Specs 07. 200% text zoom эмулируется размером текста; нативная экранная клавиатура не проверялась. Просмотр документа остаётся честной заглушкой. Live CRUD использует временную demo БД и реальные server-generated UUID; проект `c2dd7f25-0269-4d52-80c8-d4360a63da2b` оставлен для review.
