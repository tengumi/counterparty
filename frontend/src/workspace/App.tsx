import { useState } from "react";
import type { Candidate } from "../types";
import { Action, Icon } from "../components/Primitives";
import { ChatPanel } from "../components/ChatPanel";
import {
  EvidenceDrawer,
  type SourceDetails,
} from "../components/EvidenceDrawer";
import { CompanyReport } from "../comparison/CompanyReport";
import { ComparisonTable } from "../comparison/ComparisonTable";
import { ProjectPanel } from "../projects/ProjectPanel";
import { CreateProjectDialog } from "../projects/CreateProjectDialog";
import { SelectionSummary } from "./SelectionSummary";
import { useWorkspace } from "./useWorkspace";

export function App() {
  const w = useWorkspace();
  const { data, busy, project, shortlist } = w;
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<SourceDetails | null>(null);
  const [creating, setCreating] = useState(false);
  const [chatExpanded, setChatExpanded] = useState(false);
  const [mobilePane, setMobilePane] = useState<"reports" | "chat">("chat");
  const choose = (candidate: Candidate, selectionId?: string) =>
    w.send(
      {
        candidate_snapshot_id: candidate.snapshot_id,
        ...(selectionId ? { candidate_selection_id: selectionId } : {}),
      },
      `Выбрана компания: ${candidate.full_name}`,
    );
  const cards = data?.comparison ? data.cards : data?.card ? [data.card] : [];
  const selected = cards.length > 0;
  const unresolved =
    data?.comparison_selections.filter((s) => s.status !== "resolved") || [];
  const selectionPending =
    !!data?.comparison_pending ||
    !!unresolved.length ||
    !!data?.candidates.length;
  const projectView = project && w.view === "project";
  const projectIds = project?.shortlist_ids.length
    ? project.shortlist_ids
    : project?.snapshot_ids || [];
  const dialogueCards = projectView
    ? projectIds.flatMap((id) =>
        cards.filter((card) => card.snapshot_id === id),
      )
    : cards;
  const dialogueFocus = projectView
    ? project.focused_snapshot_id || null
    : data?.focus_snapshot_id || null;
  const focusedCompany = dialogueCards.find(
    (card) => card.snapshot_id === dialogueFocus,
  );
  const detailedCard = projectView
    ? focusedCompany ||
      (!dialogueFocus && dialogueCards.length === 1 ? dialogueCards[0] : null)
    : data?.card;
  const projectScope = focusedCompany
    ? `Обсуждаем: ${focusedCompany.short_name || focusedCompany.name} · отчёты и документы`
    : dialogueFocus
      ? "Выбранная компания недоступна в текущем составе"
      : `Вся группа проекта · компаний: ${dialogueCards.length}`;
  const focusCompany = (position: number, selection = cards) => {
    setMobilePane("chat");
    if (projectView) {
      const company = selection[position - 1];
      if (company) void w.command("set_focus", { value: company.snapshot_id });
    } else void w.send({ question: `Покажи карточку №${position}` });
  };
  const search = (
    <section className="search-section" aria-label="Поиск компаний">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (busy || !query.trim()) return;
          // Список и свободную фразу различает сервер: запятая может быть частью условий.
          void w.send({ question: query });
        }}
      >
        <Icon name="search" />
        <label className="sr-only" htmlFor="company-query">
          ИНН, ОГРН или название компании
        </label>
        <input
          id="company-query"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="ИНН, ОГРН или название компании"
          maxLength={12000}
          disabled={busy}
          required
        />
        <Action type="submit" view="primary" disabled={busy || !query.trim()}>
          Найти
        </Action>
      </form>
      <p className="small muted">Можно описать задачу своими словами.</p>
    </section>
  );
  return (
    <div className={`app-shell ${selected ? "has-selection" : "is-start"}`}>
      <header className="app-header">
        <a href="/" className="brand">
          <span className="brand-mark">А</span>
          <span>
            Проверка контрагентов
            <span className="brand-sub">Помощник для бизнеса</span>
          </span>
        </a>
        <nav className="header-actions" aria-label="Управление проверкой">
          {!!w.projects.length && (
            <details className="saved-projects">
              <summary>Сохранённые проверки</summary>
              <div className="saved-project-list">
                {w.projects.map((p) => (
                  <button
                    key={p.project_id}
                    disabled={busy}
                    onClick={() => void w.openProject(p.project_id)}
                  >
                    {p.title}
                  </button>
                ))}
              </div>
            </details>
          )}
          {(selected || project) && (
            <Action
              disabled={busy}
              onClick={() => {
                void w.reset();
                setQuery("");
                setSource(null);
                setChatExpanded(false);
                setMobilePane("chat");
              }}
            >
              <Icon name="plus" />
              Новая проверка
            </Action>
          )}
        </nav>
      </header>
      <main className="main-workspace">
        {!selected && (
          <div className="search-start">
            <span className="eyebrow">Перед тем как начать сотрудничество</span>
            <h1>Кого проверим?</h1>
            <p className="start-description">
              Найдите компанию или сравните несколько.
              <br />
              Помощник разберёт отчёты с учётом вашей задачи.
            </p>
            {search}
          </div>
        )}
        <div className="workspace-content">
          {w.error && (
            <div className="error-banner" role="alert">
              {w.error}
            </div>
          )}
          {busy && !selected && (
            <p className="loading-bar" role="status">
              Ищем доступные данные…
            </p>
          )}
          {!selected && data?.answer && !selectionPending && (
            <p className="search-answer" role="status">
              {data.answer}
            </p>
          )}
          {selectionPending && (
            <section
              className="surface selection-confirmation"
              aria-label="Подтверждение компаний"
            >
              {!!data?.candidates.length && (
                <div className="candidate-list">
                  <h2>Уточните компанию</h2>
                  <p className="small muted">
                    Проверьте название и реквизиты перед анализом.
                  </p>
                  {data.candidates.map((c) => (
                    <button
                      key={c.snapshot_id}
                      disabled={busy}
                      onClick={() => choose(c)}
                    >
                      <strong>{c.full_name}</strong>
                      <span>
                        ИНН {c.inn} · ОГРН {c.ogrn || "не указан"}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {unresolved.map((s) => (
                <div className="candidate-list" key={s.selection_id}>
                  <h3>Компания №{s.position}</h3>
                  <p>{s.message}</p>
                  {s.candidates.map((c) => (
                    <button
                      key={c.snapshot_id}
                      disabled={busy}
                      onClick={() => choose(c, s.selection_id)}
                    >
                      <strong>{c.full_name}</strong>
                      <span>
                        ИНН {c.inn} · ОГРН {c.ogrn || "не указан"}
                      </span>
                    </button>
                  ))}
                </div>
              ))}
              {data?.comparison_pending &&
                !unresolved.length &&
                !data.candidates.length && (
                  <p className="notice">{data.answer}</p>
                )}
            </section>
          )}
          {(selected || project) && (
            <>
              <div className="check-heading">
                <div>
                  <span className="eyebrow">
                    {project ? "Сохранённая проверка" : "Текущая проверка"}
                  </span>
                  <h1>
                    {project?.title ||
                      (cards.length > 1
                        ? `Сравниваем компании · ${cards.length}`
                        : data?.card?.short_name ||
                          data?.card?.name ||
                          "Проверка")}
                  </h1>
                </div>
                {!project && selected && (
                  <button
                    className="text-button"
                    disabled={busy || selectionPending}
                    onClick={() => setCreating(true)}
                  >
                    Сохранить проверку
                  </button>
                )}
              </div>
              {project && (
                <div className="workspace-views">
                  <button
                    className={w.view === "comparison" ? "active" : ""}
                    onClick={() => w.setView("comparison")}
                  >
                    Диалог по отчётам
                  </button>
                  <button
                    className={w.view === "project" ? "active" : ""}
                    onClick={() => w.setView("project")}
                  >
                    Проверка с документами
                    {project.proposal && <i className="new-dot" />}
                  </button>
                </div>
              )}
              <nav className="workspace-panels" aria-label="Рабочая область">
                <button
                  aria-pressed={mobilePane === "reports"}
                  aria-controls="check-reports"
                  onClick={() => setMobilePane("reports")}
                >
                  <Icon name="file" />
                  {data?.comparison ? "Сравнение" : "Отчёт"}
                </button>
                <button
                  aria-pressed={mobilePane === "chat"}
                  aria-controls="check-dialogue"
                  onClick={() => setMobilePane("chat")}
                >
                  <Icon name="chat" /> Чат
                  {busy && <span className="chat-activity" />}
                </button>
              </nav>
              <div
                className="check-layout"
                data-chat-expanded={chatExpanded}
                data-mobile-pane={mobilePane}
              >
                <div className="check-reports" id="check-reports">
                  {dialogueCards.length > 1 && (
                    <details className="participants-disclosure">
                      <summary>
                        Выбранные компании <span>{dialogueCards.length}</span>
                      </summary>
                      <SelectionSummary
                        cards={dialogueCards}
                        focused={dialogueFocus}
                        busy={busy || selectionPending}
                        source={setSource}
                        focus={(n) => focusCompany(n, dialogueCards)}
                      />
                    </details>
                  )}
                  {selected && (
                    <div className="surface reports-surface">
                      {data?.comparison && (
                        <ComparisonTable
                          data={data}
                          shortlist={shortlist}
                          setShortlist={w.setShortlist}
                          source={setSource}
                          focus={focusCompany}
                          busy={busy || selectionPending}
                        />
                      )}
                      {detailedCard && (
                        <CompanyReport card={detailedCard} source={setSource} />
                      )}
                    </div>
                  )}
                  {projectView && (
                    <details
                      className="report-disclosure project-disclosure"
                      open
                    >
                      <summary>
                        <span>
                          Документы и резюме проверки
                          <small>
                            План, открытые вопросы и сохранение результата
                          </small>
                        </span>
                        <Icon name="plus" />
                      </summary>
                      <ProjectPanel
                        key={`${project.project_id}:${project.goal}`}
                        project={project}
                        busy={busy}
                        command={w.command}
                        upload={w.upload}
                        cards={cards}
                        source={setSource}
                      />
                    </details>
                  )}
                  <details className="additional-search">
                    <summary>Поиск по реквизитам</summary>
                    {search}
                  </details>
                  <p className="workspace-footnote">
                    Выводы основаны на доступных данных. Решение о
                    сотрудничестве остаётся за вами.
                  </p>
                </div>
                <div className="check-dialogue" id="check-dialogue">
                  {dialogueFocus && (projectView || data?.comparison) && (
                    <div className="focus-return">
                      <Action
                        disabled={busy || selectionPending}
                        onClick={() =>
                          projectView
                            ? void w.command("set_focus", { value: "" })
                            : void w.send({ question: "Покажи сравнение" })
                        }
                      >
                        ← Обсудить всю группу
                      </Action>
                    </div>
                  )}
                  <ChatPanel
                    messages={w.messages}
                    busy={busy}
                    send={w.ask}
                    group={dialogueCards.length > 1 && !dialogueFocus}
                    source={setSource}
                    pending={selectionPending}
                    expanded={chatExpanded}
                    toggleExpanded={() => setChatExpanded((value) => !value)}
                    review={
                      projectView && project.deal
                        ? {
                            ...project.deal,
                            steps: project.plan.map((step) => step.title),
                          }
                        : data?.review
                    }
                    scope={
                      projectView
                        ? projectScope
                        : data?.card
                          ? data.card.short_name || data.card.name
                          : `Вся группа · компаний: ${cards.length}`
                    }
                  />
                </div>
              </div>
            </>
          )}
        </div>
      </main>
      {source && (
        <EvidenceDrawer details={source} close={() => setSource(null)} />
      )}
      {creating && (
        <CreateProjectDialog
          busy={busy}
          initialGoal={data?.review?.goal || ""}
          close={() => setCreating(false)}
          create={async (title, goal) => {
            if (await w.createProject(title, goal)) setCreating(false);
          }}
        />
      )}
    </div>
  );
}
