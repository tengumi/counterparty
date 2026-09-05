import { Link, useParams } from 'react-router-dom';
import { AgentChat } from '../chat/AgentChat';
import styles from '../App.module.css';

export function CheckPage() {
  const { projectId, threadId } = useParams();
  const isDemo = projectId === 'demo-project' && (!threadId || threadId === 'demo-thread');

  return (
    <>
      <header className={styles.header}>
        <Link to="/checks">← Все проверки</Link>
        <span>{isDemo ? 'Поставка оборудования к 20 сентября' : 'Проверка'}</span>
      </header>
      <section className={styles.content}>
        <h1>{isDemo ? 'Разговор о поставке' : 'Разговор'}</h1>
        <p className={styles.subtitle}>{isDemo ? 'Учебный пример' : 'Демонстрационная оболочка'}</p>
        <div className={styles.card}>
          <h2>Обсудите задачу с помощником</h2>
          {isDemo ? (
            <AgentChat projectId={projectId!} threadId={threadId ?? 'demo-thread'} />
          ) : (
            <>
              <p>Здесь будут разговор, сведения о компаниях и материалы проверки.</p>
              <p className={styles.muted}>Разговор пока недоступен. Данные проверки не загружены.</p>
            </>
          )}
        </div>
      </section>
    </>
  );
}
