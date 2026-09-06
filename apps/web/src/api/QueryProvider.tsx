import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ApiProject } from './contracts';
import { workspaceKeys } from './workspace';

export function WorkspaceQueryProvider({
  children,
  initialProjects,
}: {
  children: React.ReactNode;
  initialProjects?: readonly ApiProject[];
}) {
  const [client] = useState(() => {
    const next = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } },
    });
    if (initialProjects) {
      next.setQueryData(workspaceKeys.all, initialProjects);
      for (const project of initialProjects) next.setQueryData(workspaceKeys.project(project.id), project);
    }
    return next;
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
