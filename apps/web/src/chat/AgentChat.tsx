/**
 * Minimal chat surface built from assistant-ui primitives.
 *
 * The spike keeps styling deliberately plain: it exists to prove the transport
 * renders text, typed activity and terminal state, not to be the final screen.
 */

import { useMemo } from 'react';
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
} from '@assistant-ui/react';
import { useAgentRuntime } from './useAgentRuntime';
import type { AgentRuntimeOptions } from './useAgentRuntime';
import type { PublicAgentState } from './publicAgentState';
import { emptyAgentState } from './publicAgentState';
import { useAgentProjection } from './useAgentProjection';
import styles from './AgentChat.module.css';

function ActivityTrail({ fallback }: { fallback: PublicAgentState }) {
  const { activities, run } = useAgentProjection(fallback);

  return (
    <section aria-label="Ход проверки" className={styles.trail}>
      <ul className={styles.activities}>
        {activities.map((activity) => (
          <li key={activity.id} data-status={activity.status} data-kind={activity.kind}>
            {activity.label}
          </li>
        ))}
      </ul>
      {run?.error ? (
        <p className={styles.error} role="alert">
          {run.error.message}
        </p>
      ) : null}
      <p className={styles.status}>
        Статус: <span data-testid="run-status">{run?.status ?? 'нет запуска'}</span>
      </p>
    </section>
  );
}

function Messages() {
  return (
    <ThreadPrimitive.Messages
      components={{
        UserMessage: () => (
          <article className={styles.user}>
            <MessagePrimitive.Parts />
          </article>
        ),
        AssistantMessage: () => (
          <article className={styles.assistant}>
            <MessagePrimitive.Parts />
          </article>
        ),
      }}
    />
  );
}

export function AgentChat(props: AgentRuntimeOptions) {
  const runtime = useAgentRuntime(props);
  const fallback = useMemo(
    () => emptyAgentState(props.projectId, props.threadId),
    [props.projectId, props.threadId],
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className={styles.root}>
        <ThreadPrimitive.Viewport className={styles.viewport}>
          <Messages />
        </ThreadPrimitive.Viewport>
        <ActivityTrail fallback={fallback} />
        <ComposerPrimitive.Root className={styles.composer}>
          <ComposerPrimitive.Input
            aria-label="Сообщение помощнику"
            className={styles.input}
            placeholder="Спросите о контрагенте"
          />
          <ComposerPrimitive.Send className={styles.send}>Отправить</ComposerPrimitive.Send>
          <ComposerPrimitive.Cancel className={styles.send}>Остановить</ComposerPrimitive.Cancel>
        </ComposerPrimitive.Root>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
