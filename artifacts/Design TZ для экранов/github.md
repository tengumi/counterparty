repo: core-ds/core-components
branch: master

secondary_repo: core-ds/ui-primitives
secondary_path: icons/glyph
secondary_commit: 9587916dcae6073cc49e572614a556b1baf210ae

## Last sync
date: 2026-09-04T13:31:07Z

### Updated in this project
- Добавлены glyph_cross_s, glyph_chevron-down_s, glyph_arrow-up_s, glyph_arrow-down_s, glyph_arrow-up_m — все рукописные иконки интерфейса заменены официальными (осталась только внутренняя отметка Checkbox)
- Типографика сведена к пяти ступеням Core DS: 24/32 · 20/28 · 16/24 · 14/20 · 13/18 · 12/16
- Добавлено живое обсуждение проекта: тред с вводом, контекстом модели, follow-up и выходом в memo и план агента
- Вытащены токены bluetint-темы (цвета, типографика, радиусы, отступы, тени) из `packages/vars`
- Прочитаны стили Table, Button, Tabs, StatusBadge, Tag, FilterTag, Checkbox, Input, Plate, PureCell, Steps, SidePanel, Link, ProgressBar
- Скопировано 25 официальных glyph-иконок из `ui-primitives@9587916` без изменений (`icons/`), атрибуция в `icons/ATTRIBUTION.md`
- Экраны собраны как продуктовые паттерны на этих примитивах, значения перенесены литералами

## Sync history
- 2026-09-03T21:37:56Z — токены Core DS и первые 20 glyph-иконок

## Screen map
| Экран проекта | Файлы репозитория |
|---|---|
| Сравнение контрагентов (таблица) | packages/table/src/components/{table,thead,thead-cell,trow,tcell,tsortable-head-cell}/index.module.css |
| Вкладки проекта | packages/tabs/src/vars.css, packages/tabs/src/components/primary-tablist/index.module.css |
| Кнопки и действия | packages/button/src/vars.css, packages/button/src/components/base-button/*.css, packages/button/src/desktop/*.css |
| Риск-индикаторы | packages/status-badge/src/{index,default}.module.css |
| Evidence-чипы, фильтры | packages/tag/src/vars.css, packages/tag/src/components/native-tag/default.module.css, packages/filter-tag/src/desktop/desktop.module.css |
| Evidence drawer | packages/side-panel/src/vars.css, packages/side-panel/src/components/header/index.module.css |
| Ограничения трактовки | packages/plate/src/components/base-plate/index.module.css, packages/alert/src/index.module.css |
| План агента, документы | packages/steps/src/components/step/index.module.css, packages/pure-cell/src/index.module.css, packages/progress-bar/src/index.module.css |
| Чекбоксы shortlist | packages/checkbox/src/styles/{index,default}.module.css |
| Токены | packages/vars/src/{colors-bluetint,typography,typography-vars,border-radius,gaps,common,shadows-indigo}.css |
| Иконки всех экранов | core-ds/ui-primitives@9587916 icons/glyph/glyph_*.svg (25 файлов) |
