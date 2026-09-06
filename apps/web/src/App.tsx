import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { ChecksPage } from './pages/ChecksPage';
import { CheckPage } from './pages/CheckPage';
import { WorkspaceQueryProvider } from './api/QueryProvider';
import type { ApiProject } from './api/contracts';
import styles from './App.module.css';
import { SessionGate } from './auth/SessionGate';
import { ChecksSidebar } from './components/ChecksSidebar';

function AppShell() {
  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#content">К содержимому</a>
      <ChecksSidebar />
      <main className={styles.main} id="content" tabIndex={-1}><Outlet /></main>
    </div>
  );
}

export function App({ initialProjects, fixtureMode = false, requireSession = false }: { initialProjects?: readonly ApiProject[]; fixtureMode?: boolean; requireSession?: boolean }) {
  const routes = (
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/checks" replace />} />
          <Route path="/checks" element={<ChecksPage />} />
          <Route path="/checks/:projectId" element={<CheckPage fixtureMode={fixtureMode} />} />
          <Route path="/checks/:projectId/chats/:threadId" element={<CheckPage fixtureMode={fixtureMode} />} />
          <Route path="*" element={
            <section className={styles.content}>
              <h1>Страница не найдена</h1>
              <Link to="/checks">Все проверки</Link>
            </section>
          } />
        </Route>
      </Routes>
  );
  return (
    <WorkspaceQueryProvider initialProjects={initialProjects}>
      {requireSession ? <SessionGate>{routes}</SessionGate> : routes}
    </WorkspaceQueryProvider>
  );
}
