/**
 * Conversation blocks of S2 (07 §5) rendered from typed data.
 *
 * The renderers never invent a fact: a statement carries a numbered basis or
 * no basis at all, and the panel resolves the reference. The live agent
 * projection is mapped onto the same block union, so the source can be swapped
 * for REST/stream without touching these components.
 */

import { useId, useState } from 'react';
import { Button } from '@alfalab/core-components/button';
import type {
  ActivityStep,
  AnswerPoint,
  ConversationBlock,
} from '../../../mocks/types';
import { findEvidence } from '../../../mocks/workspace';
import styles from './Conversation.module.css';

export interface ConversationActions {
  /** Opens the numbered basis in the materials panel (07 P1-03). */
  readonly onOpenEvidence: (evidenceId: string) => void;
  /** Puts editable text into the composer; it never sends by itself. */
  readonly onInsertDraft: (text: string) => void;
  readonly onFocusComposer: () => void;
  readonly onOpenDocument: (documentId: string) => void;
  /** Opens «Итог» in the materials panel; recording a decision is D1. */
  readonly onOpenSummary: () => void;
}

function EvidenceLink({
  point,
  onOpenEvidence,
}: {
  point: AnswerPoint;
  onOpenEvidence: (evidenceId: string) => void;
}) {
  const record = findEvidence(point.evidenceId);
  if (record === undefined) return null;
  return (
    <button
      aria-label={`Основание ${record.number}: ${record.title}`}
      className={styles.evidence}
      onClick={() => onOpenEvidence(record.id)}
      type="button"
    >
      {record.number}
    </button>
  );
}

function Points({
  points,
  onOpenEvidence,
}: {
  points: readonly AnswerPoint[];
  onOpenEvidence: (evidenceId: string) => void;
}) {
  if (points.length === 0) return null;
  return (
    <ul className={styles.points}>
      {points.map((point) => (
        <li className={styles.point} key={point.id}>
          <span aria-hidden="true" className={styles.pointDash}>
            —
          </span>
          <span>
            {point.text}
            <EvidenceLink onOpenEvidence={onOpenEvidence} point={point} />
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * S2-05 progress: one current line plus the completed steps on request.
 *
 * Only finished steps are listed, because «Что проверено» answers what has
 * been done — not what the model is thinking. Stopping the run lives next to
 * the composer, so there is exactly one place that cancels.
 */
export function ActivityBlock({
  label,
  status,
  steps,
}: {
  label: string;
  status: 'running' | 'completed' | 'failed';
  steps: readonly ActivityStep[];
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const done = steps.filter((step) => step.status !== 'running');
  const failed = done.some((step) => step.status === 'failed');

  // A finished run speaks for itself through its answer. Keep the trail while
  // it works, when something went wrong, or when there is a real multi-step
  // sequence worth inspecting — but not a bare «Проверка завершена» line under
  // an answer that already stands on its own.
  if (status === 'completed' && !failed && done.length < 2) return null;

  return (
    <section aria-label="Ход проверки" className={styles.activity}>
      <p className={styles.activityLine}>
        <span aria-hidden="true" className={styles.dot} data-status={status} />
        <span>{label}</span>
        {done.length > 0 ? (
          <Button
            aria-controls={listId}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            size={32}
            view="text"
          >
            Что проверено
          </Button>
        ) : null}
      </p>
      {done.length > 0 ? (
        <ul className={styles.steps} hidden={!open} id={listId}>
          {done.map((step) => (
            <li className={styles.step} key={step.id}>
              <span
                className={styles.stepLabel}
                data-kind={step.kind ?? undefined}
                data-status={step.status}
              >
                {step.label}
              </span>
              <span className={styles.stepSource}>{step.source}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Block({
  block,
  actions,
}: {
  block: ConversationBlock;
  actions: ConversationActions;
}) {
  switch (block.kind) {
    case 'resume':
      return (
        <div className={styles.resume}>
          <p className={styles.resumeLabel}>Остановились на…</p>
          <p className={styles.resumeText}>{block.text}</p>
          <span className={styles.resumeAction}>
            <Button onClick={actions.onFocusComposer} size={40} view="primary">
              Продолжить
            </Button>
          </span>
        </div>
      );

    case 'user':
      return (
        <div className={styles.user}>
          {block.context !== null ? <span className={styles.chip}>{block.context}</span> : null}
          <p className={styles.bubble}>{block.text}</p>
          {block.file !== null ? (
            <span className={styles.file}>
              <span>
                <span className={styles.fileName}>{block.file.name}</span>
                <span className={styles.fileState}>{block.file.state}</span>
              </span>
            </span>
          ) : null}
        </div>
      );

    case 'notice':
      return (
        <p className={styles.notice}>
          <span>{block.text}</span>
          {block.action !== null ? (
            <Button
              onClick={() => actions.onOpenDocument(block.action?.documentId ?? '')}
              size={32}
              view="text"
            >
              {block.action.label}
            </Button>
          ) : null}
        </p>
      );

    case 'activity':
      return <ActivityBlock label={block.label} status={block.status} steps={block.steps} />;

    case 'answer':
      return (
        <div className={styles.answer}>
          <p className={styles.answerText}>{block.text}</p>
          <Points onOpenEvidence={actions.onOpenEvidence} points={block.points} />
          {block.followUp !== null ? <p className={styles.answerText}>{block.followUp}</p> : null}
          {block.options.length > 0 ? (
            <div className={styles.options}>
              {block.options.map((option) => (
                <Button
                  key={option.id}
                  onClick={() => actions.onInsertDraft(option.text)}
                  size={40}
                  view="outlined"
                >
                  {option.label}
                </Button>
              ))}
            </div>
          ) : null}
        </div>
      );

    case 'conclusion':
      return (
        <div className={styles.conclusion}>
          <p className={styles.conclusionLabel}>Вывод по вашей задаче</p>
          {block.stale ? <p className={styles.stale}>Сделан для прежних условий</p> : null}
          <p className={styles.answerText}>{block.text}</p>
          <Points onOpenEvidence={actions.onOpenEvidence} points={block.points} />
          {block.unconfirmed !== null ? (
            <p className={styles.unconfirmed}>{block.unconfirmed}</p>
          ) : null}
          <span>
            <Button onClick={actions.onOpenSummary} size={40} view="outlined">
              Зафиксировать решение
            </Button>
          </span>
        </div>
      );

    case 'confirmation':
      return (
        <div className={styles.confirmation}>
          <p className={styles.answerText}>{block.text}</p>
          <div className={styles.confirmationActions}>
            <Button onClick={actions.onOpenSummary} size={40} view="outlined">
              {block.attachLabel}
            </Button>
            <Button
              onClick={() => actions.onInsertDraft('Документа нет')}
              size={40}
              view="secondary"
            >
              {block.declineLabel}
            </Button>
          </div>
        </div>
      );
  }
}

export function ConversationFeed({
  blocks,
  actions,
}: {
  blocks: readonly ConversationBlock[];
  actions: ConversationActions;
}) {
  if (blocks.length === 0) return null;
  return (
    <div className={styles.feed}>
      {blocks.map((block) => (
        <div className={styles.block} key={block.id}>
          <Block actions={actions} block={block} />
        </div>
      ))}
    </div>
  );
}

/** Honest empty state: nothing has been said in this chat yet. */
export function EmptyConversation() {
  return (
    <div className={styles.empty}>
      <p>Сообщений пока нет.</p>
      <p>Напишите вопрос или вставьте ИНН — помощник ответит по сведениям проверки.</p>
    </div>
  );
}
