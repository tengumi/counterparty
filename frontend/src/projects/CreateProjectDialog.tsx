import { useEffect, useRef, useState } from "react";
import { Action } from "../components/Primitives";

export function CreateProjectDialog({
  close,
  create,
  busy,
}: {
  close: () => void;
  create: (title: string, goal: string) => void;
  busy: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog className="create-dialog" ref={dialog} onCancel={close}>
      <h2>Сохранить проверку как проект</h2>
      <p className="muted">
        Состав компаний, отбор и документы будут доступны при следующем
        открытии.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          create(title, goal);
        }}
      >
        <label>
          Название проекта
          <input
            autoFocus
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={120}
            placeholder="Например: поставщик оборудования"
            disabled={busy}
          />
        </label>
        <label>
          Цель проверки
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            maxLength={2000}
            placeholder="Что важно выяснить перед сделкой?"
            rows={3}
            disabled={busy}
          />
        </label>
        <div className="inline-actions">
          <Action onClick={close} disabled={busy}>
            Отмена
          </Action>
          <Action type="submit" view="primary" disabled={busy || !title.trim()}>
            Создать проект
          </Action>
        </div>
      </form>
    </dialog>
  );
}
