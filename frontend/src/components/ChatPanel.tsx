import { useEffect, useRef, useState } from "react";
import type { Message } from "../types";
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
}: {
  messages: Message[];
  busy: boolean;
  send: (question: string) => void;
  group: boolean;
  source: (details: SourceDetails) => void;
  scope?: string;
}) {
  const [question, setQuestion] = useState("");
  const conversation = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (messages.length) scrollConversation(conversation.current);
  }, [messages, busy]);
  return (
    <aside className="assistant-panel" aria-label="AI-помощник">
      <header className="assistant-header">
        <span className="assistant-symbol">
          <Icon name="spark" />
        </span>
        <div>
          <strong>Помощник</strong>
          <p className="small muted">
            {scope ||
              (group ? "По выбранным контрагентам" : "По данным проверки")}
          </p>
        </div>
      </header>
      <div
        ref={conversation}
        className="conversation"
        role="log"
        aria-live="polite"
      >
        {!messages.length && (
          <div className="chat-welcome">
            <h3>Разберёмся в деталях</h3>
            <p className="muted">
              Помогу найти важное в отчётах, сопоставить факты и увидеть, каких
              данных не хватает.
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
        <div className="question-hints">
          {(group
            ? ["У кого есть убыток?", "Какие пробелы в данных по группе?"]
            : ["Какие риски?", "Какая выручка?"]
          ).map((q) => (
            <button disabled={busy} key={q} onClick={() => send(q)}>
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
            placeholder="Спросите о контрагентах…"
            maxLength={12000}
            disabled={busy}
            rows={2}
          />
          <Action
            view="primary"
            type="submit"
            disabled={busy || !question.trim()}
            aria-label="Отправить запрос"
          >
            <Icon name="arrow" />
          </Action>
        </form>
        <p className="small muted chat-disclaimer">
          Ответы ограничены доступными данными
        </p>
      </div>
    </aside>
  );
}
