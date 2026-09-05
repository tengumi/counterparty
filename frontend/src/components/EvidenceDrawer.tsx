import { useEffect, useRef } from "react";
import type { Evidence } from "../types";
import { Action, date, Icon } from "./Primitives";

export interface SourceDetails {
  title: string;
  value: string;
  company?: string;
  evidence: Evidence[];
}
export function EvidenceDrawer({
  details,
  close,
}: {
  details: SourceDetails;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  const sources = [
    ...new Map(
      details.evidence.map((e) => [
        `${e.company_name}:${e.source_name}:${e.report_at}:${e.quality}`,
        e,
      ]),
    ).values(),
  ];
  const coverage: Record<string, string> = {
    present: "Основание присутствует в отчёте",
    empty: "Передан пустой раздел",
    missing: "Сведений недостаточно",
    not_applicable: "Показатель неприменим",
    unknown: "Полнота покрытия неизвестна",
    provided: "Текст предоставлен пользователем",
  };
  const quality: Record<string, string> = {
    confirmed:
      "Извлечение и расчёт проверены; истинность сведений поставщика не подтверждается",
    partial: "Данные неполные",
    conflicting: "Есть противоречия в данных",
  };
  return (
    <dialog
      ref={dialog}
      className="source-drawer"
      onCancel={close}
      onClick={(e) => {
        if (e.target === dialog.current) close();
      }}
    >
      <div className="drawer-inner">
        <div className="section-heading">
          <span className="eyebrow">Основание показателя</span>
          <Action onClick={close} aria-label="Закрыть источник">
            <Icon name="close" />
          </Action>
        </div>
        <h2>{details.title}</h2>
        {details.company && <p className="muted">{details.company}</p>}
        <p className="source-value">{details.value}</p>
        {sources.map((item, i) => (
          <section className="source-block" key={i}>
            {item.company_name && (
              <p className="source-owner">{item.company_name}</p>
            )}
            <strong>
              {["user_document", "user_context"].includes(item.quality)
                ? item.source_name
                : "Отчёт о контрагенте"}
            </strong>
            <p>
              {item.quality === "user_document"
                ? "Загружен"
                : item.quality === "user_context"
                  ? "Сообщено"
                  : "Данные на"}{" "}
              {date(item.report_at)}
            </p>
            <p className="muted">
              {item.quality === "user_document"
                ? "Документ пользователя; его подлинность не проверялась."
                : item.quality === "user_context"
                  ? "Условия, которые вы сообщили в этой проверке. Это не данные отчёта."
                  : "Состояние и полнота данных учитываются при анализе."}
            </p>
            <p className="small">
              {coverage[item.coverage] || "Покрытие не определено"}
            </p>
            {quality[item.quality] && (
              <p className="small muted">{quality[item.quality]}</p>
            )}
          </section>
        ))}
        <p className="muted small">
          Отсутствие сведений не означает отсутствие риска.
        </p>
      </div>
    </dialog>
  );
}
