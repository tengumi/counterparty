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
import { useWorkspace } from "./useWorkspace";

export function App() {
  const w = useWorkspace();
  const { data, busy, project, shortlist } = w;
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<SourceDetails | null>(null);
  const [creating, setCreating] = useState(false);
  const choose = (candidate: Candidate, selectionId?: string) =>
    w.send(
      {
        candidate_snapshot_id: candidate.snapshot_id,
        ...(selectionId ? { candidate_selection_id: selectionId } : {}),
      },
      `Выбрана компания: ${candidate.full_name}`,
    );
  const cards = data?.comparison ? data.cards : data?.card ? [data.card] : [];
  return (
    <div className="app-shell">
      <nav className="sidebar" aria-label="Рабочее пространство">
        <a href="/" className="brand">
          <span className="brand-mark">А</span>
          <span>
            Бизнес<span className="brand-sub">Проверка контрагентов</span>
          </span>
        </a>
        <div className="sidebar-section">
          <span className="eyebrow">Рабочее пространство</span>
          <button
            className={`nav-item ${!project ? "active" : ""}`}
            disabled={busy}
            onClick={() => w.setView("comparison")}
          >
            <Icon name="grid" />
            Текущая проверка
          </button>
          <button
            className="nav-item"
            onClick={() => {
              w.reset();
              setQuery("");
            }}
            disabled={busy}
          >
            <Icon name="plus" />
            Новая проверка
          </button>
        </div>
        {!!w.projects.length && (
          <div className="project-list">
            <span className="eyebrow">Проекты</span>
            {w.projects.map((p) => (
              <button
                className={`nav-item ${project?.project_id === p.project_id ? "active" : ""}`}
                key={p.project_id}
                onClick={() => w.openProject(p.project_id)}
                disabled={busy}
              >
                <Icon name="folder" />
                <span>{p.title}</span>
              </button>
            ))}
          </div>
        )}
        <div className="sidebar-bottom">
          <span className={`status-dot ${w.health ? "online" : ""}`} />
          <span>
            {w.health
              ? `${w.health.companies_count} отчётов доступно`
              : "Подключение к источнику"}
          </span>
          <p>Локальное рабочее пространство</p>
        </div>
      </nav>
      <main className="main-workspace">
        <header className="workspace-header">
          <div>
            <span className="eyebrow">
              Контрагенты / {project ? "Проект" : "Проверка"}
            </span>
            <h1>
              {project?.title ||
                (data?.comparison
                  ? "Сравнение контрагентов"
                  : data?.card
                    ? "Проверка контрагента"
                    : "Новая проверка")}
            </h1>
          </div>
          {!project && (
            <Action disabled={busy} onClick={() => setCreating(true)}>
              <Icon name="folder" />
              Сохранить проект
            </Action>
          )}
        </header>
        <div className="workspace-content">
          {project && (
            <div className="workspace-views">
              <button
                className={w.view === "comparison" ? "active" : ""}
                onClick={() => w.setView("comparison")}
              >
                Контрагенты · {cards.length}
              </button>
              <button
                className={w.view === "project" ? "active" : ""}
                onClick={() => w.setView("project")}
              >
                Проект проверки{project.proposal && <i className="new-dot" />}
              </button>
            </div>
          )}
          {w.error && (
            <div className="error-banner" role="alert">
              {w.error}
            </div>
          )}
          {busy && (
            <p className="loading-bar" role="status">
              Обрабатываем запрос…
            </p>
          )}
          {project && w.view === "project" ? (
            <ProjectPanel
              key={`${project.project_id}:${project.goal}`}
              project={project}
              busy={busy}
              command={w.command}
              upload={w.upload}
              cards={cards}
              source={setSource}
            />
          ) : (
            <>
              <section className="search-section">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const text =
                      /[;,\n]/.test(query) && !/^сравни/i.test(query)
                        ? `Сравни ${query}`
                        : query;
                    w.send({ question: text });
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
                  <Action
                    type="submit"
                    view="primary"
                    disabled={busy || !query.trim()}
                  >
                    Проверить
                  </Action>
                </form>
                <p className="small muted">
                  Для сравнения добавьте несколько компаний через точку с
                  запятой
                </p>
              </section>
              <div className="surface">
                {!!data?.candidates.length && (
                  <div className="candidate-list">
                    <h2>Какая компания вам нужна?</h2>
                    {data.candidates.map((c) => (
                      <button
                        key={c.snapshot_id}
                        disabled={busy}
                        onClick={() => choose(c)}
                      >
                        <strong>{c.full_name}</strong>
                        <span>ИНН {c.inn}</span>
                      </button>
                    ))}
                  </div>
                )}
                {data?.comparison_selections
                  .filter((s) => s.status !== "resolved")
                  .map((s) => (
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
                          <span>ИНН {c.inn}</span>
                        </button>
                      ))}
                    </div>
                  ))}
                {data?.comparison && (
                  <>
                    <ComparisonTable
                      data={data}
                      shortlist={shortlist}
                      setShortlist={w.setShortlist}
                      source={setSource}
                      focus={(n) =>
                        w.send({ question: `Покажи карточку №${n}` })
                      }
                      busy={busy}
                    />
                  </>
                )}
                {data?.card && (
                  <>
                    {data.comparison && (
                      <div className="focus-return">
                        <Action
                          onClick={() =>
                            w.send({ question: "Покажи сравнение" })
                          }
                          disabled={busy}
                        >
                          ← Вернуться к группе
                        </Action>
                      </div>
                    )}
                    <CompanyReport card={data.card} source={setSource} />
                  </>
                )}
                {!cards.length &&
                  !data?.candidates.length &&
                  !data?.comparison_selections.length && (
                    <div className="blank-state">
                      <div className="blank-icon">
                        <Icon name="grid" />
                      </div>
                      <h2>От списка компаний — к решению</h2>
                      <p>
                        Найдите контрагентов, сравните важные показатели
                        <br />и оставьте подходящих кандидатов в отборе.
                      </p>
                      <div className="empty-steps">
                        <span>
                          <b>1</b>Добавьте компании
                        </span>
                        <span>
                          <b>2</b>Сравните факты
                        </span>
                        <span>
                          <b>3</b>Уточните детали
                        </span>
                      </div>
                    </div>
                  )}
              </div>
            </>
          )}
          <p className="workspace-footnote">
            Банковский светофор и факты отчёта — отдельно. Решение о
            сотрудничестве остаётся за вами.
          </p>
        </div>
      </main>
      <ChatPanel
        messages={w.messages}
        busy={busy}
        send={w.ask}
        group={!!data?.comparison && !data.focus_snapshot_id}
        source={setSource}
        scope={
          project && w.view === "project"
            ? `Проект · ${shortlist.length || cards.length} компаний и документы`
            : undefined
        }
      />
      {source && (
        <EvidenceDrawer details={source} close={() => setSource(null)} />
      )}
      {creating && (
        <CreateProjectDialog
          busy={busy}
          close={() => setCreating(false)}
          create={async (title, goal) => {
            if (await w.createProject(title, goal)) setCreating(false);
          }}
        />
      )}
    </div>
  );
}
