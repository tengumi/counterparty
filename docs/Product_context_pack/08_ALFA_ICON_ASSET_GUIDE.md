# Alfa/Core DS: набор SVG-иконок для продукта проверки контрагентов

Актуальность исследования: **03.09.2026**.

## Короткий вывод

Для интерфейса следует использовать основной официальный набор
`@alfalab/icons-glyph`, а не архивный `@alfalab/icons-classic` и не сторонние
«похожие» библиотеки. Каноническая цепочка публикации подтверждена README
официального репозитория:

1. исходные SVG — [`core-ds/ui-primitives`](https://github.com/core-ds/ui-primitives/tree/9587916dcae6073cc49e572614a556b1baf210ae/icons/glyph);
2. генерация React-компонентов — [`core-ds/icons`](https://github.com/core-ds/icons/tree/8dc42ac147a72a59b3c02b74f01066ddc18e7123/packages/glyph/src);
3. публикация — [`@alfalab/icons-glyph`](https://www.npmjs.com/package/@alfalab/icons-glyph), версия `2.289.0` на дату проверки;
4. официальный поиск по каталогу — [Core DS Icons Demo](https://core-ds.github.io/icons-demo/).

[`core-ds/core-components`](https://github.com/core-ds/core-components) и его
[Storybook](https://core-ds.github.io/core-components/) — официальный источник
UI-компонентов и паттернов, но не первичный источник SVG. Старый
[`alfa-laboratory/icons`](https://github.com/alfa-laboratory/icons) архивирован;
его пакет `@alfalab/icons` версии `3.26.0` не брать за актуальную основу.

## Как импортировать

Официальный README задаёт прямой импорт по имени компонента:

```tsx
import { ExclamationCircleMIcon } from '@alfalab/icons-glyph/ExclamationCircleMIcon';
// также поддерживается default import из того же пути
```

Компоненты `@alfalab/icons-glyph` используют `fill="currentColor"`; цвет нужно
задавать через CSS `color`. Приложенные raw SVG сохранены без изменений и
содержат исходные `#000000`, `#0B1F35` или `black`; не выдавать перекрашенную
копию за исходный файл.

## Статусы mapping

- **official / exact** — официальный SVG и прямое соответствие смыслу поверхности;
- **official / reuse** — официальный SVG, но смысл шире или уже требуемого;
- **fallback-композиция** — отдельных точных символов нет; в UI рядом используются
  две официальные иконки. Новый объединённый SVG не создаётся.

## Практический mapping

| Поверхность | Компонент и прямой package path | Raw SVG в наборе | Статус и применение |
|---|---|---|---|
| Компания | `OfficeMIcon` — `@alfalab/icons-glyph/OfficeMIcon` | `office_m.svg` | official / reuse; карточка юрлица, не использовать как логотип |
| Сравнение компаний | `ArrowsUpDownMIcon` + `OfficeMIcon` | `arrows-up-down_m.svg`, `office_m.svg` | fallback-композиция; две иконки рядом, не накладывать друг на друга |
| Отчёт / evidence | `DocumentLinesLineMIcon` — `@alfalab/icons-glyph/DocumentLinesLineMIcon` | `document-lines-line_m.svg` | official / exact |
| Фильтры | `FilterMIcon` — `@alfalab/icons-glyph/FilterMIcon` | `filter_m.svg` | official / exact |
| Риск / предупреждение | `ExclamationCircleMIcon` — `@alfalab/icons-glyph/ExclamationCircleMIcon` | `exclamation-circle_m.svg` | official / exact; тяжесть кодировать цветом и текстом, не одной иконкой |
| Финансы | `ChartColumnThreeMIcon` — `@alfalab/icons-glyph/ChartColumnThreeMIcon` | `chart-column-three_m.svg` | official / exact; для финансового блока, не для комплаенс-светофора |
| Суды / арбитраж | `JudgeHammerMIcon` — `@alfalab/icons-glyph/JudgeHammerMIcon` | `judge-hammer_m.svg` | official / exact |
| Исполнительные производства | `DocumentBanknoteMIcon` — `@alfalab/icons-glyph/DocumentBanknoteMIcon` | `document-banknote_m.svg` | official / reuse; обозначает денежный документ, поэтому всегда нужна подпись «Исполнительные производства» |
| Документы / добавление файла | `DocumentAddMIcon` — `@alfalab/icons-glyph/DocumentAddMIcon` | `document-add_m.svg` | official / reuse; годится для upload CTA с текстовой подписью, отдельный `UploadMIcon` в текущем glyph-наборе не найден |
| Чат | `BubbleLinesLineMIcon` — `@alfalab/icons-glyph/BubbleLinesLineMIcon` | `bubble-lines-line_m.svg` | official / exact |
| AI-помощник | `RobotMIcon` — `@alfalab/icons-glyph/RobotMIcon` | `robot_m.svg` | official / exact; не применять как общий декоративный brand mark |
| Проект / рабочая папка | `FolderMIcon` — `@alfalab/icons-glyph/FolderMIcon` | `folder_m.svg` | official / exact |
| Память проекта | `FolderMIcon` + текст «Память проекта» | `folder_m.svg` | official / reuse; отдельного проверенного memory-символа не найдено |
| План агента | `ListBulletedMIcon` — `@alfalab/icons-glyph/ListBulletedMIcon` | `list-bulleted_m.svg` | official / exact |
| Выполненный шаг / прогресс | `CheckmarkCircleLineMIcon` — `@alfalab/icons-glyph/CheckmarkCircleLineMIcon` | `checkmark-circle-line_m.svg` | official / exact; текущий процесс показывать loader/progress-компонентом, не галочкой |
| MCP / подключение | `ChainCircleMIcon` — `@alfalab/icons-glyph/ChainCircleMIcon` | `chain-circle_m.svg` | official / reuse; обязательно подписывать названием коннектора |
| OAuth / доступ | `KeyMIcon` — `@alfalab/icons-glyph/KeyMIcon` | `key_m.svg` | official / reuse; не заменяет статус авторизации |
| Внешний источник | `InternetMIcon` — `@alfalab/icons-glyph/InternetMIcon` | `internet_m.svg` | official / reuse; показывать рядом с названием реестра/URL |
| Дата / актуальность | `ClockLineMIcon` — `@alfalab/icons-glyph/ClockLineMIcon` | `clock-line_m.svg` | official / exact |
| Нет данных по документу | `DocumentUnknownMIcon` — `@alfalab/icons-glyph/DocumentUnknownMIcon` | `document-unknown_m.svg` | official / exact; нейтральный серый, не красный риск |
| Неизвестно / нужна проверка | `QuestionCircleLineMIcon` — `@alfalab/icons-glyph/QuestionCircleLineMIcon` | `question-circle-line_m.svg` | official / exact; текстом пояснить, чего именно не хватает |

## Правила для макетов

1. Базовый размер набора — `24 × 24` (`MIcon`). Не масштабировать ниже `20 px`;
   если нужен компактный размер, сначала проверить существование официального
   `SIcon`, а не ужимать `MIcon`.
2. Иконка не заменяет текст для рисков, статуса авторизации, источника и
   отсутствующих данных.
3. Не кодировать зелёный/жёлтый/красный риск формой иконки. Использовать один
   `ExclamationCircleMIcon`, а уровень передавать токеном цвета, лейблом и
   доступным текстом.
4. Для ЗСК и банковского светофора не создавать новые цветные SVG: цвет —
   состояние компонента, шкалы должны оставаться раздельными.
5. Для декоративных иконок ставить `aria-hidden="true"`; для icon-only кнопки —
   доступное имя на кнопке (`aria-label`).
6. Не смешивать `classic`, `rocky` и `glyph` в одной поверхности без решения
   дизайн-системы. Этот набор целиком из `glyph`.
7. Для fallback-композиции использовать две самостоятельные иконки и подпись;
   не модифицировать path и не называть результат официальной Alfa-иконкой.

## Состав локального набора

Каталог: `alfa_icon_assets/`.

```text
arrows-up-down_m.svg
bubble-lines-line_m.svg
chain-circle_m.svg
chart-column-three_m.svg
checkmark-circle-line_m.svg
clock-line_m.svg
document-add_m.svg
document-banknote_m.svg
document-lines-line_m.svg
document-unknown_m.svg
exclamation-circle_m.svg
filter_m.svg
folder_m.svg
internet_m.svg
judge-hammer_m.svg
key_m.svg
list-bulleted_m.svg
office_m.svg
question-circle-line_m.svg
robot_m.svg
```

Все 20 файлов — byte-for-byte копии соответствующих `icons/glyph/glyph_*.svg`
из `core-ds/ui-primitives` commit `9587916…`; локально удалён только префикс
`glyph_` из имени файла. Условия и атрибуция сохранены в
`alfa_icon_assets/ATTRIBUTION.md`.

## Проверка и ограничения

- Имена всех 20 React-компонентов проверены по реально существующим файлам
  `packages/glyph/src/*Icon.tsx` в `core-ds/icons` commit `8dc42ac…`.
- Версии `@alfalab/icons-glyph@2.289.0` и `@alfalab/icons@3.492.0`, а также
  лицензия MIT проверены через npm registry 03.09.2026.
- В исследованной ревизии `ui-primitives` поле `license` в `package.json` — MIT,
  но отдельного файла `LICENSE` в корне нет. Перед production-дистрибуцией
  рекомендуется проверка внутренней open-source политики.
- Иконки не подтверждают визуальное совпадение с закрытым интерфейсом
  «Альфа-Бизнес»: это официальная публичная Core DS-библиотека, а не извлечение
  ассетов из продукта.
