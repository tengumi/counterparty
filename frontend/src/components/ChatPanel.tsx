import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Message, ReviewContext } from "../types";
import { Action, Icon } from "./Primitives";
import type { SourceDetails } from "./EvidenceDrawer";

export function scrollConversation(
  container: Pick<HTMLElement, "scrollTop" | "scrollHeight"> | null,
) {
  // Прокручиваем только сообщения, не уводим всю страницу от карточки к чату.
  if (container) container.scrollTop = container.scrollHeight;
}

export function submitChatOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
  // Во время ввода иероглифов Enter подтверждает символ, а не отправляет вопрос.
  if (
    event.key !== "Enter" ||
    event.shiftKey ||
    event.nativeEvent.isComposing ||
    event.nativeEvent.keyCode === 229
  )
    return;
  event.preventDefault();
  if (!event.repeat) event.currentTarget.form?.requestSubmit();
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
  expanded = false,
  toggleExpanded,
}: {
  messages: Message[];
  busy: boolean;
  send: (question: string) => void;
  group: boolean;
  source: (details: SourceDetails) => void;
  scope?: string;
  review?: ReviewContext | null;
  pending?: boolean;
  expanded?: boolean;
  toggleExpanded?: () => void;
}) {
  const [question, setQuestion] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);
  const returnFocus = useRef(false);
  const conversation = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (busy || pending || !returnFocus.current) return;
    // После ответа продолжаем ввод с клавиатуры, не отнимая фокус у других кнопок.
    if (document.activeElement === document.body)
      textarea.current?.focus({ preventScroll: true });
    returnFocus.current = false;
  }, [busy, pending]);
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
          <Icon name="chat" />
        </span>
        <div>
          <strong>Помощник</strong>
          <p className="small muted">
            {scope ||
              (group ? "По выбранным контрагентам" : "По данным проверки")}
          </p>
        </div>
        {toggleExpanded && (
          <button
            type="button"
            className="chat-expand"
            onClick={toggleExpanded}
            aria-pressed={expanded}
            aria-label={expanded ? "Вернуть чат сбоку" : "Расширить чат"}
            title={expanded ? "Вернуть чат сбоку" : "Расширить чат"}
          >
            <Icon name={expanded ? "minimize" : "expand"} />
            <span>{expanded ? "Сбоку" : "Расширить"}</span>
          </button>
        )}
      </header>
      {review && (review.goal || review.general_check) && (
        <details className="review-context" aria-label="Условия проверки">
          <summary>
            <span>Ваша задача</span>
            <strong>{review.goal || "Общая проверка"}</strong>
          </summary>
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
          {!!review.steps.length && (
            <div className="review-steps">
              <p>Что проверено</p>
              <ul>
                {review.steps.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ul>
            </div>
          )}
        </details>
      )}
      <div
        ref={conversation}
        className="conversation"
        role="log"
        aria-label="Сообщения проверки"
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
            if (!busy && !pending && question.trim()) {
              returnFocus.current = document.activeElement === textarea.current;
              send(question.trim());
              setQuestion("");
            }
          }}
        >
          <label className="sr-only" htmlFor="chat-question">
            Запрос помощнику
          </label>
          <textarea
            ref={textarea}
            id="chat-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={submitChatOnEnter}
            aria-describedby="chat-keyboard-hint"
            placeholder="Опишите задачу или задайте вопрос…"
            maxLength={12000}
            disabled={busy || pending}
            rows={2}
          />
          <div className="composer-actions">
            <span id="chat-keyboard-hint">
              Enter — отправить · Shift+Enter — новая строка
            </span>
            <Action
              view="primary"
              type="submit"
              disabled={busy || pending || !question.trim()}
              aria-label="Отправить запрос"
            >
              <Icon name="arrow" />
            </Action>
          </div>
        </form>
        <p className="small muted chat-disclaimer">
          Ответы ограничены доступными данными
        </p>
      </div>
    </section>
  );
}
