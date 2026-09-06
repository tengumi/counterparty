import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { useWorkspace } from "./useWorkspace";
import { ProjectPanel } from "../projects/ProjectPanel";
import type { Card, ChatResponse, Project, ReviewContext } from "../types";

vi.mock("./useWorkspace", () => ({ useWorkspace: vi.fn() }));
vi.mock("@alfalab/core-components-button", () => ({
  Button: ({ children, ...props }: { children: import("react").ReactNode }) =>
    createElement("button", props, children),
}));

const card: Card = {
  snapshot_id: "company-1",
  name: "Компания Первая",
  short_name: "Первая",
  inn: "test-1",
  ogrn: "ogrn-1",
  report_at: "2026-09-01T00:00:00Z",
  raw_status: "CURRENT",
  party_type: "LEGAL",
  bank_risk: { display_level: "YELLOW", raw_level: "YELLOW" },
  findings: [],
  evidence: [],
};
const review: ReviewContext = {
  goal: "Выбрать поставщика",
  role: "Поставщик",
  subject: "Оборудование",
  amount: "2 млн рублей",
  advance: "50%",
  deadline: "30 дней",
  general_check: false,
  question: null,
  steps: ["Проверены сведения о компании", "Сопоставлены доступные показатели"],
  context_revision: 1,
};
function response(values: Partial<ChatResponse> = {}): ChatResponse {
  return {
    session_id: "session",
    answer: "Для чего проверяете компанию?",
    status: "analyzed",
    llm_used: false,
    card,
    cards: [],
    candidates: [],
    comparison: null,
    comparison_selections: [],
    focus_snapshot_id: null,
    comparison_pending: false,
    answer_claims: [],
    ...values,
  };
}
function workspace(data: ChatResponse | null = null) {
  vi.mocked(useWorkspace).mockReturnValue({
    data,
    busy: false,
    project: null,
    projects: [],
    shortlist: [],
    messages: [],
    error: "",
    health: null,
    view: "comparison",
    setView: vi.fn(),
    setShortlist: vi.fn(),
    send: vi.fn(),
    ask: vi.fn(),
    reset: vi.fn(),
    openProject: vi.fn(),
    createProject: vi.fn(),
    command: vi.fn(),
    upload: vi.fn(),
  });
}
const render = () => renderToStaticMarkup(createElement(App));
const project: Project = {
  project_id: "project",
  title: "Поставка",
  goal: "Выбрать поставщика",
  revision: 2,
  shortlist_ids: [],
  snapshot_ids: [card.snapshot_id],
  session_id: "session",
  updated_at: "2026-09-01",
  documents: [],
  plan_mode: "ai",
  plan: [],
  questions: [],
  memo: null,
  proposal: null,
};
const renderProject = (value: Project) =>
  renderToStaticMarkup(
    createElement(ProjectPanel, {
      project: value,
      busy: false,
      command: vi.fn(),
      upload: vi.fn(),
      cards: [card],
      source: vi.fn(),
    }),
  );

describe("Поиск → задача → диалог → подробности", () => {
  it("проектный фокус не подменяется фокусом обычного чата и сбрасывается ко всей группе", () => {
    const second = {
      ...card,
      snapshot_id: "company-2",
      name: "Компания Вторая",
      short_name: "Вторая",
      inn: "test-2",
    };
    workspace(
      response({
        cards: [card, second],
        comparison: {
          snapshot_ids: [card.snapshot_id, second.snapshot_id],
          rows: [],
          financial_year: null,
          limitations: [],
        },
        card,
        focus_snapshot_id: card.snapshot_id,
      }),
    );
    const current = vi.mocked(useWorkspace).getMockImplementation()!();
    const scoped = {
      ...project,
      snapshot_ids: [card.snapshot_id, second.snapshot_id],
      focused_snapshot_id: second.snapshot_id,
    };
    vi.mocked(useWorkspace).mockReturnValue({
      ...current,
      project: scoped,
      view: "project",
    });
    let html = render();
    expect(html).toContain("Обсуждаем: Вторая · отчёты и документы");
    expect(html).toContain('aria-pressed="true">Вторая</button>');
    expect(html).toContain("Обсудить всю группу");
    const detailed = html.slice(html.indexOf('aria-label="Отчёт о компании"'));
    expect(detailed).toContain("Вторая");
    expect(detailed).not.toContain("Компания Первая");
    vi.mocked(useWorkspace).mockReturnValue({
      ...current,
      project: { ...scoped, focused_snapshot_id: null },
      view: "project",
    });
    html = render();
    expect(html).toContain("Вся группа проекта · компаний: 2");
    expect(html).not.toContain("Обсудить всю группу");
    expect(html).not.toContain("Обсуждаем: Первая");
  });
  it("пустой диалог не спрашивает цель повторно, когда условия уже сохранены", () => {
    workspace(response({ review }));
    const html = render();
    expect(html).toContain("Задача сохранена");
    expect(html).not.toContain("Расскажите, зачем проверяете компанию");
    expect(html).not.toContain("Что вы хотите выяснить?");
  });
  it("помечает сохранённое резюме устаревшим после изменения условий", () => {
    const html = renderProject({
      ...project,
      memo_stale: true,
      memo: {
        goal: project.goal,
        created_at: "2026-09-01",
        note: "Резюме",
        selected_snapshot_ids: project.snapshot_ids,
        document_hashes: {},
        items: [],
      },
    });
    expect(html).toContain("После сохранения изменились условия");
    expect(html).not.toContain("Принять изменения");
  });
  it("сохраняет ответы на уточнения и не показывает отвеченный вопрос как незаполненный", () => {
    const html = renderProject({
      ...project,
      questions: [
        {
          question_id: "payment",
          text: "Какой аванс?",
          document_ids: [],
          answer: "Без аванса",
          status: "answered",
        },
      ],
    });
    expect(html).toContain("Ваш ответ: Без аванса");
    expect(html).toContain("Ответ учтён");
    expect(html).toContain("Изменить ответ");
    expect(html).not.toContain("Учесть ответ");
  });
  it("предложенное резюме показывает вывод и условия, не теряя новые типы пунктов", () => {
    const html = renderProject({
      ...project,
      proposal: {
        proposal_id: "proposal",
        base_revision: 2,
        diff: [],
        memo: {
          goal: "Поставка",
          created_at: "2026-09-01",
          note: "Черновик",
          selected_snapshot_ids: [card.snapshot_id],
          document_hashes: {},
          items: [
            {
              kind: "analysis",
              text: "Важен срок исполнения",
              evidence_ids: [],
              company_id: null,
            },
            {
              kind: "condition",
              text: "Вы указали оплату после поставки",
              evidence_ids: [],
              company_id: null,
            },
          ],
        },
      },
    });
    expect(html).toContain("Важен срок исполнения");
    expect(html).toContain("Вы указали оплату после поставки");
    expect(html).toContain("Принять изменения");
    expect(html).not.toContain("Из пользовательских документов");
  });
  beforeEach(() => workspace());
  it("во время анализа показывает ожидание и не допускает параллельную отправку", () => {
    workspace(response());
    const current = vi.mocked(useWorkspace).getMockImplementation()!();
    vi.mocked(useWorkspace).mockReturnValue({ ...current, busy: true });
    const html = render();
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("Проверяю доступные данные");
    expect(html).toMatch(/<textarea[^>]*id="chat-question"[^>]*disabled/);
  });
  it("до выбора показывает только вход и не предлагает диалог без компании", () => {
    const html = render();
    expect(html).toContain("Кого проверим?");
    expect(html).toContain("ИНН, ОГРН или название компании");
    expect(html).toContain("Можно описать задачу своими словами.");
    expect(html).not.toContain("через точку с запятой");
    expect(html).not.toContain('aria-label="Помощник по проверке"');
    expect(html).not.toContain("Сохранить проверку");
  });
  it("неоднозначность разрешается по названию и реквизитам до диалога", () => {
    workspace(
      response({
        card: null,
        candidates: [
          {
            snapshot_id: card.snapshot_id,
            full_name: card.name,
            inn: card.inn,
            ogrn: card.ogrn,
          },
        ],
      }),
    );
    const html = render();
    expect(html).toContain("Уточните компанию");
    expect(html).toContain("ОГРН ogrn-1");
    expect(html).not.toContain('aria-label="Помощник по проверке"');
  });
  it("после выбора сводка видна рядом с единственным чатом, детали раскрываются внутри отчёта", () => {
    workspace(response());
    const html = render();
    expect(html.indexOf('aria-label="Отчёт о компании"')).toBeLessThan(
      html.indexOf('aria-label="Помощник по проверке"'),
    );
    expect(html).not.toContain('<details class="report-disclosure">');
    expect(html).toContain('aria-label="Расширить чат"');
    expect(html).toContain('aria-controls="check-reports"');
    expect(html).toContain('aria-controls="check-dialogue"');
    expect(html.match(/id="chat-question"/g)).toHaveLength(1);
    expect(html).toContain('aria-describedby="chat-keyboard-hint"');
    expect(html).toContain("Shift+Enter — новая строка");
    expect(html).toContain("Общая проверка");
    expect(html).toContain("Выбираю поставщика");
    expect(html).not.toContain("Методика закрыта");
  });
  it("показывает сохранённые условия и их изменение без повторного запроса цели", () => {
    workspace(response({ review }));
    expect(render()).toContain("50%");
    expect(render()).not.toContain("Выбираю поставщика");
    workspace(
      response({
        review: { ...review, advance: "Без аванса", context_revision: 2 },
      }),
    );
    const html = render();
    expect(html).toContain("Без аванса");
    expect(html).not.toContain("50%");
    expect(html).toContain("Что проверено");
  });
  it("pending-добавление сохраняет группу, кандидатов и блокирует преждевременный групповой ответ", () => {
    workspace(
      response({
        card: null,
        cards: [card],
        comparison: {
          snapshot_ids: [card.snapshot_id],
          rows: [],
          financial_year: null,
          limitations: [],
        },
        comparison_pending: true,
        comparison_selections: [
          {
            selection_id: "addition",
            position: 2,
            status: "ambiguous",
            message: "Уточните вторую компанию",
            candidates: [
              {
                snapshot_id: "candidate",
                full_name: "Кандидат",
                inn: "test-2",
                ogrn: "ogrn-2",
              },
            ],
          },
        ],
      }),
    );
    const html = render();
    expect(html).toContain("Текущий состав сохранён");
    expect(html).toContain("ИНН test-1");
    expect(html).toContain("ОГРН ogrn-2");
    expect(html).toMatch(/<textarea[^>]*id="chat-question"[^>]*disabled/);
  });
});
