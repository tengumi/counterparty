import { useState } from "react";
import type { Project, Card } from "../types";
import { Action, date, Icon } from "../components/Primitives";
import type { SourceDetails } from "../components/EvidenceDrawer";

export function ProjectPanel({
  project,
  busy,
  command,
  upload,
  cards,
  source,
}: {
  project: Project;
  busy: boolean;
  command: (action: string, values?: Record<string, unknown>) => void;
  upload: (file: File) => void;
  cards: Card[];
  source: (details: SourceDetails) => void;
}) {
  const [tab, setTab] = useState("plan");
  const [goal, setGoal] = useState(project.goal);
  const [showOld, setShowOld] = useState(false);
  const [showChanges, setShowChanges] = useState(false);
  const memo = project.proposal?.memo || project.memo;
  const selected = project.shortlist_ids.length || project.snapshot_ids.length;
  const stale =
    project.memo &&
    (project.memo.goal !== project.goal ||
      JSON.stringify(project.memo.selected_snapshot_ids) !==
        JSON.stringify(
          project.shortlist_ids.length
            ? project.shortlist_ids
            : project.snapshot_ids,
        ) ||
      project.documents.some(
        (d) => project.memo!.document_hashes[d.document_id] !== d.content_hash,
      ));
  const showItem = (item: NonNullable<typeof memo>["items"][number]) => {
    const evidence = [
      ...new Map(
        [
          ...cards.flatMap((c) => c.evidence),
          ...(project.memo?.sources || []),
          ...(project.proposal?.memo.sources || []),
        ].map((e) => [e.evidence_id, e]),
      ).values(),
    ].filter((e) => item.evidence_ids.includes(e.evidence_id));
    for (const doc of project.documents)
      for (const fragment of doc.fragments)
        if (
          item.evidence_ids.includes(fragment.evidence_id) &&
          !evidence.some((e) => e.evidence_id === fragment.evidence_id)
        )
          evidence.push({
            evidence_id: fragment.evidence_id,
            report_at: doc.uploaded_at,
            source_name: doc.name,
            canonical_path: fragment.location,
            quality: "user_document",
            coverage: "provided",
          });
    source({
      title:
        item.kind === "document" ? "Пользовательский документ" : "Факт резюме",
      value: item.text,
      evidence,
    });
  };
  return (
    <section className="project-panel">
      <div className="project-goal">
        <span className="eyebrow">Цель проверки</span>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            command("set_goal", { value: goal });
          }}
        >
          <textarea
            rows={2}
            aria-label="Цель проверки"
            placeholder="Например: выбрать поставщика для сделки с авансом"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            maxLength={2000}
            disabled={busy}
          />
          <Action disabled={busy || goal === project.goal} type="submit">
            Сохранить
          </Action>
        </form>
      </div>
      <div className="project-tabs" role="tablist" aria-label="Разделы проекта">
        {[
          ["plan", "План проверки"],
          ["documents", `Документы · ${project.documents.length}`],
          ["memo", "Резюме"],
        ].map(([id, label]) => (
          <button
            role="tab"
            aria-selected={tab === id}
            key={id}
            onClick={() => setTab(id)}
          >
            {label}
            {id === "memo" && project.proposal && <i className="new-dot" />}
          </button>
        ))}
      </div>
      {tab === "plan" && (
        <div className="project-section">
          <div className="section-heading">
            <div>
              <h2>Углублённая проверка</h2>
              <p className="small muted">
                {project.shortlist_ids.length
                  ? "Компаний в отборе"
                  : "Всех компаний проекта"}
                : {selected}
              </p>
            </div>
            <Action
              view="primary"
              disabled={busy || !project.goal.trim() || !selected}
              onClick={() => command("run")}
            >
              <Icon name="spark" />
              Запустить
            </Action>
          </div>
          {!project.plan.length && (
            <p className="muted">
              Проверка прочитает отчёты, выделит факты по цели и учтёт
              документы. Результат — предложение резюме, которое вы сможете
              принять.
            </p>
          )}
          <ol className="plan-list">
            {project.plan.map((s, i) => (
              <li key={s.step_id}>
                <span className={`step-icon ${s.status}`}>
                  {s.status === "complete"
                    ? "✓"
                    : s.status === "limited"
                      ? "!"
                      : i + 1}
                </span>
                <div>
                  <strong>{s.title}</strong>
                  <p className="small muted">{s.detail}</p>
                </div>
              </li>
            ))}
          </ol>
          {!!project.plan.length && (
            <p className="small muted">
              {project.plan_mode === "ai"
                ? "Темы подобраны помощником по цели. Факты проверены сервером."
                : "Выполнен базовый план: модель недоступна или не выбрала допустимые темы."}
            </p>
          )}
          {!!project.questions.length && (
            <div className="open-questions">
              <h3>Что ещё уточнить</h3>
              {project.questions.map((q) => (
                <div key={q.question_id}>
                  <p>{q.text}</p>
                  <span className="small muted">
                    {q.document_ids.length
                      ? `Документов связано: ${q.document_ids.length}. Требует вашего подтверждения.`
                      : "Нет связанного документа"}
                  </span>
                </div>
              ))}
            </div>
          )}
          {project.proposal && (
            <button className="memo-callout" onClick={() => setTab("memo")}>
              <Icon name="file" />
              <span>
                <strong>Предложение резюме готово</strong>
                <small>Посмотрите изменения перед сохранением</small>
              </span>
              <Icon name="arrow" />
            </button>
          )}
        </div>
      )}
      {tab === "documents" && (
        <div className="project-section">
          <div className="section-heading">
            <div>
              <h2>Документы проекта</h2>
              <p className="small muted">
                TXT, Markdown, PDF или DOCX · до 2 МБ · до 5 файлов
              </p>
            </div>
            <label className={`upload-button ${busy ? "disabled" : ""}`}>
              <Icon name="plus" />
              Добавить файл
              <input
                type="file"
                aria-label="Добавить документ"
                accept=".txt,.md,.pdf,.docx"
                disabled={busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) upload(file);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
          {!project.documents.length && (
            <p className="muted">
              Прикрепите предложение или договор для уточнения деталей. Документ
              не меняет данные банковского отчёта.
            </p>
          )}
          {project.documents.map((doc) => (
            <article className="document-row" key={doc.document_id}>
              <Icon name="file" />
              <div>
                <strong>{doc.name}</strong>
                <p className="small muted">{doc.note}</p>
                <details>
                  <summary>Посмотреть текст документа</summary>
                  <div className="document-text">
                    {doc.fragments.map((f) => (
                      <p key={f.evidence_id}>
                        <span className="small muted">{f.location}</span>
                        <br />
                        {f.text}
                      </p>
                    ))}
                  </div>
                </details>
                {!!project.questions.length && (
                  <select
                    aria-label={`Связать с вопросом: ${doc.name}`}
                    value={doc.question_id || ""}
                    disabled={busy}
                    onChange={(e) =>
                      e.target.value &&
                      command("link_document", {
                        document_id: doc.document_id,
                        question_id: e.target.value,
                      })
                    }
                  >
                    <option value="">Связать с открытым вопросом</option>
                    {project.questions.map((q) => (
                      <option key={q.question_id} value={q.question_id}>
                        {q.text}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
      {tab === "memo" && (
        <div className="project-section">
          <div className="section-heading">
            <div>
              <h2>
                {project.proposal
                  ? "Предлагаемое резюме"
                  : "Сохранённое резюме"}
              </h2>
              <p className="small muted">
                {memo
                  ? `Подготовлено ${date(memo.created_at)}`
                  : "Появится после запуска плана"}
              </p>
            </div>
            {project.proposal && (
              <Action
                view="primary"
                disabled={busy}
                onClick={() =>
                  command("accept_memo", {
                    proposal_id: project.proposal!.proposal_id,
                  })
                }
              >
                Принять изменения
              </Action>
            )}
          </div>
          {project.proposal && (
            <p className="notice">
              Это предложение. Сохранённое резюме пока не изменено.
            </p>
          )}
          {!project.proposal && stale && (
            <p className="notice">
              После сохранения изменились цель, состав или документы. Запустите
              план, чтобы обновить резюме.
            </p>
          )}
          {!memo && (
            <p className="muted">
              Опишите цель и запустите проверку на вкладке «План проверки».
            </p>
          )}
          {project.proposal && (
            <div className="memo-view-controls">
              <button
                className="text-button"
                onClick={() => setShowChanges(!showChanges)}
              >
                {showChanges ? "Скрыть изменения" : "Показать изменения"}
              </button>
              {project.memo && (
                <button
                  className="text-button"
                  onClick={() => setShowOld(!showOld)}
                >
                  {showOld ? "Скрыть прежнюю версию" : "Прежняя версия"}
                </button>
              )}
            </div>
          )}
          {showOld && project.memo && (
            <div className="old-memo">
              <h3>Прежняя версия</h3>
              {project.memo.items.map((item, i) => (
                <p key={i}>{item.text}</p>
              ))}
            </div>
          )}
          {showChanges && project.proposal && (
            <div className="memo-diff">
              {project.proposal.diff.map((d, i) => (
                <p className={d.kind} key={i}>
                  {d.kind === "add" ? "+ " : "− "}
                  {d.text}
                </p>
              ))}
            </div>
          )}
          {memo && (
            <>
              <p className="memo-goal">Цель: {memo.goal}</p>
              {(["fact", "document", "limitation", "action"] as const).map(
                (kind) => (
                  <div className="memo-section" key={kind}>
                    <h3>
                      {
                        {
                          fact: "Факты отчётов",
                          document: "Из пользовательских документов",
                          limitation: "Ограничения",
                          action: "Следующие действия",
                        }[kind]
                      }
                    </h3>
                    {memo.items
                      .filter((i) => i.kind === kind)
                      .map((item, i) => (
                        <div className="memo-item" key={i}>
                          <p>{item.text}</p>
                          {!!item.evidence_ids.length && (
                            <button
                              className="text-button"
                              onClick={() => showItem(item)}
                            >
                              Основание ↗
                            </button>
                          )}
                        </div>
                      ))}
                  </div>
                ),
              )}
              <p className="small muted">{memo.note}</p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
