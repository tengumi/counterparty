import { useEffect, useRef, useState } from "react";
import type { Message, ReviewContext } from "../types";
import { Action, Icon } from "./Primitives";
import type { SourceDetails } from "./EvidenceDrawer";

export function scrollConversation(
  container: Pick<HTMLElement, "scrollTop" | "scrollHeight"> | null,
) {
  // Прокручиваем только сообщения, не уводим всю страницу от карточки к чату.
  if (container) container.scrollTop = container.scrollHeight;
}

export function ChatPanel({
  messages,
  busy,
  send,
  group,
  source,
  scope,
  review,
  pending = false,
}: {
  messages: Message[];
  busy: boolean;
  send: (question: string) => void;
  group: boolean;
  source: (details: SourceDetails) => void;
  scope?: string;
  review?: ReviewContext | null;
  pending?: boolean;
}) {
  const [question, setQuestion] = useState("");
  const conversation = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (messages.length) scrollConversation(conversation.current);
  }, [messages, busy]);
  return (
    <section
      className="assistant-panel"
      aria-label="Помощник по проверке"
      aria-busy={busy}
    >
      <header className="assistant-header">
        <span className="assistant-symbol">
          <Icon name="file" />
        </span>
        <div>
          <strong>Разберём вашу задачу</strong>
          <p className="small muted">
            {scope ||
              (group ? "По выбранным контрагентам" : "По данным проверки")}
          </p>
        </div>
      </header>
      {review && (review.goal || review.general_check) && (
        <div className="review-context" aria-label="Условия проверки">
          <span className="eyebrow">Ваша задача</span>
          <p>{review.goal || "Общая проверка"}</p>
          <dl>
            {(
              [
                ["Роль", review.role],
                ["Предмет", review.subject],
                ["Сумма", review.amount],
                ["Оплата", review.advance],
                ["Срок", review.deadline],
              ] as const
            )
              .filter(([, value]) => value)
              .map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
          </dl>
          <small>Сообщите в чате, если условия изменились.</small>
        </div>
      )}
      <div
        ref={conversation}
        className="conversation"
        role="log"
        aria-live="polite"
      >
        {!messages.length && (
          <div className="chat-welcome">
            <h3>
              {review?.goal || review?.general_check
                ? "Продолжим проверку"
                : "Что вы хотите выяснить?"}
            </h3>
            <p className="muted">
              {review?.question ||
                (review?.goal || review?.general_check
                  ? "Задача сохранена. Задайте вопрос по выбранным компаниям или приложите документ к проверке."
                  : "Расскажите, зачем проверяете компанию. Можно начать с общей проверки без условий сделки.")}
            </p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            <span className="message-label">
              {m.role === "user" ? "Вы" : "Помощник"}
            </span>
            <div>{m.text}</div>
            {!!m.evidence?.length && (
              <button
                className="text-button"
                onClick={() =>
                  source({
                    title: "На чём основан ответ",
                    value: m.text,
                    evidence: m.evidence!,
                  })
                }
              >
                Источники ответа ↗
              </button>
            )}
          </div>
        ))}
        {busy && (
          <p className="working" role="status">
            Проверяю доступные данные…
          </p>
        )}
      </div>
      <div className="chat-bottom">
        {!!review?.steps.length && (
          <details className="review-steps">
            <summary>Что проверено</summary>
            <ul>
              {review.steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ul>
          </details>
        )}
        {pending && (
          <p className="notice">
            Сначала подтвердите добавляемые компании. Текущий состав сохранён.
          </p>
        )}
        <div className="question-hints">
          {(!review?.goal && !review?.general_check
            ? ["Общая проверка", "Выбираю поставщика", "Проверяю покупателя"]
            : group
              ? ["У кого есть убыток?", "Какие пробелы в данных по группе?"]
              : ["Что важно учесть?", "Что ещё проверить?"]
          ).map((q) => (
            <button disabled={busy || pending} key={q} onClick={() => send(q)}>
              {q}
            </button>
          ))}
        </div>
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            if (question.trim()) {
              send(question);
              setQuestion("");
            }
          }}
        >
          <label className="sr-only" htmlFor="chat-question">
            Запрос помощнику
          </label>
          <textarea
            id="chat-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Опишите задачу или задайте вопрос…"
            maxLength={12000}
            disabled={busy || pending}
            rows={2}
          />
          <Action
            view="primary"
            type="submit"
            disabled={busy || pending || !question.trim()}
            aria-label="Отправить запрос"
          >
            <Icon name="arrow" />
          </Action>
        </form>
        <p className="small muted chat-disclaimer">
          Ответы ограничены доступными данными
        </p>
      </div>
    </section>
  );
}
