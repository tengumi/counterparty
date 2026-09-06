import { useEffect, useState, type ReactNode } from 'react';
import { Button } from '@alfalab/core-components/button';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { requestJson, WorkspaceApiError } from '../api/client';
import styles from './SessionGate.module.css';

interface Session { login: string; display_name: string }
const sessionKey = ['session'] as const;
const unauthorized = (error: unknown) => error instanceof WorkspaceApiError && error.status === 401;

export function SessionGate({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [opened, setOpened] = useState(false);
  const session = useQuery({
    queryKey: sessionKey,
    queryFn: async () => {
      try { return (await requestJson<Session>('/auth/session')).data; }
      catch (error) { if (unauthorized(error)) return null; throw error; }
    },
    retry: false,
  });
  useEffect(() => {
    const expire = (error: unknown) => {
      if (unauthorized(error)) client.setQueryData(sessionKey, null);
    };
    const queries = client.getQueryCache().subscribe((event) => expire(event.query.state.error));
    const mutations = client.getMutationCache().subscribe((event) => expire(event.mutation?.state.error));
    return () => { queries(); mutations(); };
  }, [client]);
  const login = useMutation({
    mutationFn: async () => (await requestJson<Session>('/auth/session', {
      method: 'POST', body: JSON.stringify({ login: 'demo-analyst' }),
    })).data,
    onSuccess: (data) => {
      client.setQueryData(sessionKey, data);
      setOpened(true);
      void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'session' });
    },
  });
  const authenticated = !!session.data;
  if (authenticated && !opened) setOpened(true);
  return <>
    {(opened || authenticated) && <div hidden={!authenticated}>{children}</div>}
    {!authenticated && <main className={styles.page}>
      <section className={styles.card} aria-labelledby="sign-in-title">
        <p className={styles.brand}>Альфа-Бизнес · Демонстрация</p>
        <h1 id="sign-in-title">Проверка контрагентов</h1>
        {session.isPending ? <p role="status">Проверяем сессию…</p> : <>
          <p>{opened ? 'Сессия завершилась. Войдите снова, чтобы продолжить. Ваш черновик сохранён на этой странице.' : 'Войдите как демо-аналитик, чтобы открыть сохранённые проверки и начать новую.'}</p>
          <p className={styles.note}>Демо-вход без пароля. Сведения компаний взяты из демонстрационной базы.</p>
          {(session.isError || login.isError) && <p role="alert">Не удалось открыть сессию. Проверьте доступность сервиса и повторите попытку.</p>}
          <Button view="primary" size={48} loading={login.isPending} onClick={() => login.mutate()}>
            Войти в демо
          </Button>
        </>}
      </section>
    </main>}
  </>;
}
