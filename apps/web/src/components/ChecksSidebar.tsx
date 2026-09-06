import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@alfalab/core-components/button';
import { CrossCompactSIcon } from '@alfalab/icons-glyph/CrossCompactSIcon';
import { PlusSIcon } from '@alfalab/icons-glyph/PlusSIcon';
import { AlfaScoresIosMIcon } from '@alfalab/icons-glyph/AlfaScoresIosMIcon';
import { Link, useLocation } from 'react-router-dom';
import { listProjects } from '../api/client';
import { requestErrorMessage } from '../api/messages';
import { projectSummary, workspaceKeys } from '../api/workspace';
import { SavedChecksList } from '../screens/s1/SavedChecksList';
import styles from '../App.module.css';

function BrandMark() {
  return <span aria-hidden="true" className={styles.brandMark}><AlfaScoresIosMIcon /></span>;
}

/** Общая история использует тот же кеш проектов, что создание и переименование проверки. */
export function ChecksSidebar() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  const projects = useQuery({ queryKey: workspaceKeys.all, queryFn: listProjects, retry: false });
  const activeProjectId = /^\/checks\/([^/]+)/.exec(pathname)?.[1];

  useEffect(() => {
    if (open) closeButton.current?.focus();
  }, [open]);

  const close = () => {
    setOpen(false);
    if (open) trigger.current?.focus();
  };

  return <>
    <div className={styles.mobileBar}>
      <Link aria-label="Альфа-Бизнес — на главную" className={styles.mobileBrand} onClick={close} title="На главную" to="/checks"><BrandMark />Альфа-Бизнес</Link>
      <button aria-controls="checks-sidebar" aria-expanded={open} className={styles.historyToggle}
        onClick={() => setOpen(true)} ref={trigger} type="button">
        История проверок
      </button>
    </div>
    {open ? <button aria-label="Закрыть историю" className={styles.sidebarBackdrop} onClick={close} tabIndex={-1} type="button" /> : null}
    <aside aria-label="Навигация проверок" className={styles.sidebar} data-open={open} id="checks-sidebar" ref={sidebar}
      onKeyDown={(event) => {
        if (!open || !sidebar.current || getComputedStyle(sidebar.current).position !== 'fixed') return;
        if (event.key === 'Escape') { event.stopPropagation(); close(); }
        if (event.key !== 'Tab') return;
        const controls = [...sidebar.current.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), input:not(:disabled)')];
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }}>
      <div className={styles.sidebarTop}>
        <Link aria-label="Альфа-Бизнес — на главную" className={styles.brand} onClick={close} title="На главную" to="/checks"><BrandMark />Альфа-Бизнес</Link>
        <button aria-label="Закрыть меню истории" className={styles.sidebarClose} onClick={close} ref={closeButton} type="button">
          <CrossCompactSIcon aria-hidden="true" />
        </button>
      </div>
      <nav aria-label="Основная навигация">
        <Link aria-current={pathname === '/checks' ? 'page' : undefined} className={styles.navLink} onClick={close} to="/checks">
          Проверка контрагентов
        </Link>
      </nav>
      <Link className={styles.newCheck} onClick={close} to="/checks"><PlusSIcon aria-hidden="true" />Новая проверка</Link>
      <div className={styles.historyArea}>
        {projects.isPending ? <p className={styles.historyState} role="status">Загружаем проверки…</p> : null}
        {projects.isError ? <div className={styles.historyError} role="alert">
          <p>{requestErrorMessage(projects.error)}</p>
          <p>Это не означает, что сохранённых проверок нет.</p>
          <Button onClick={() => void projects.refetch()} size={40} view="secondary">Повторить</Button>
        </div> : null}
        {projects.data ? <SavedChecksList activeProjectId={activeProjectId} onNavigate={close} projects={projects.data.map(projectSummary)} /> : null}
      </div>
    </aside>
  </>;
}
