import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { ChecksPage } from './pages/ChecksPage';
import { CheckPage } from './pages/CheckPage';
import { WorkspaceQueryProvider } from './api/QueryProvider';
import type { ApiProject } from './api/contracts';
import styles from './App.module.css';

function AppShell() {
  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#content">К содержимому</a>
      <aside className={styles.sidebar}>
        <div className={styles.brand}><span aria-hidden="true" />Альфа-Бизнес</div>
        <nav aria-label="Основная навигация">
          <Link className={styles.navLink} to="/checks">Проверка контрагентов</Link>
        </nav>
        <p className={styles.demo}>Демонстрационная оболочка</p>
      </aside>
      <main className={styles.main} id="content" tabIndex={-1}><Outlet /></main>
    </div>
  );
}

export function App({ initialProjects }: { initialProjects?: readonly ApiProject[] }) {
  return (
    <WorkspaceQueryProvider initialProjects={initialProjects}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/checks" replace />} />
          <Route path="/checks" element={<ChecksPage />} />
          <Route path="/checks/:projectId" element={<CheckPage />} />
          <Route path="/checks/:projectId/chats/:threadId" element={<CheckPage />} />
          <Route path="*" element={
            <section className={styles.content}>
              <h1>Страница не найдена</h1>
              <Link to="/checks">Все проверки</Link>
            </section>
          } />
        </Route>
      </Routes>
    </WorkspaceQueryProvider>
  );
}
