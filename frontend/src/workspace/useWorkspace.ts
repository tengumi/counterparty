import { useEffect, useRef, useState } from "react";
import { api, post } from "../api";
import { responseSources } from "./evidence";
import type {
  ChatResponse,
  Evidence,
  Health,
  Message,
  Project,
  ProjectSummary,
  ReviewContext,
} from "../types";

const sessionKey = "counterparty.session.v2";
const projectKey = "counterparty.project.v1";
const viewKey = "counterparty.view.v1";

export function restoredWorkspaceView(
  value: string | null,
): "project" | "comparison" {
  return value === "comparison" ? "comparison" : "project";
}

export function useWorkspace() {
  const [session, setSession] = useState<string | null>(null);
  const [data, setData] = useState<ChatResponse | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [shortlist, setShortlistState] = useState<string[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [view, setViewState] = useState("comparison");
  const setView = (next: string) => {
    setViewState(next);
    sessionStorage.setItem(viewKey, next);
  };
  const pending = useRef(false);
  const requestVersion = useRef(0);

  const saveSession = (id: string) => {
    sessionStorage.setItem(sessionKey, id);
    setSession(id);
  };
  const rememberProject = (p: Project | null) => {
    setProject(p);
    setShortlistState(p?.shortlist_ids || []);
    if (p) sessionStorage.setItem(projectKey, p.project_id);
    else sessionStorage.removeItem(projectKey);
  };
  const refreshProjects = async () =>
    setProjects(await api<ProjectSummary[]>("/api/projects"));
  async function perform(job: () => Promise<void>): Promise<boolean> {
    if (pending.current) return false;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await job();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    void perform(async () => {
      const info = await api<Health>("/api/health");
      if (!active) return;
      setHealth(info);
      const previousProject = sessionStorage.getItem(projectKey);
      if (previousProject) {
        try {
          const opened = await post<{
            project: Project;
            response: ChatResponse;
          }>(`/api/projects/${previousProject}/open`, {});
          if (!active) return;
          rememberProject(opened.project);
          saveSession(opened.project.session_id);
          const restoredView = restoredWorkspaceView(
            sessionStorage.getItem(viewKey),
          );
          setView(restoredView);
          restoreAnswer(opened.response, restoredView === "project");
          await refreshProjects();
          return;
        } catch {
          sessionStorage.removeItem(projectKey);
        }
      }
      const previous = sessionStorage.getItem(sessionKey);
      if (previous) {
        try {
          const restored = await api<ChatResponse>(`/api/sessions/${previous}`);
          if (!active) return;
          restoreAnswer(restored);
          saveSession(previous);
          await refreshProjects();
          return;
        } catch {
          sessionStorage.removeItem(sessionKey);
        }
      }
      const created = await post<{ session_id: string }>("/api/sessions", {});
      if (!active) return;
      saveSession(created.session_id);
      await refreshProjects();
    });
    return () => {
      active = false;
    };
  }, []);

  function appendAnswer(result: ChatResponse) {
    const evidence = responseSources(result);
    setData(result);
    setMessages((old) => [
      ...old,
      {
        role: "assistant",
        text: result.answer,
        evidence,
      },
    ]);
  }
  function restoreAnswer(result: ChatResponse, projectDialogue = false) {
    const evidence = responseSources(result);
    setData(result);
    // Восстанавливаем ответ сервера, не создавая вымышленную историю переписки.
    setMessages(
      !projectDialogue && result.answer
        ? [{ role: "assistant", text: result.answer, evidence }]
        : [],
    );
  }
  async function send(action: Record<string, string>, label?: string) {
    if (!session) return;
    await perform(async () => {
      const version = ++requestVersion.current;
      setMessages((old) => [
        ...old,
        { role: "user", text: label || action.question },
      ]);
      const result = await post<ChatResponse>("/api/chat", {
        session_id: session,
        ...action,
      });
      if (version !== requestVersion.current) return;
      appendAnswer(result);
      const ids = result.comparison
        ? result.comparison.snapshot_ids
        : result.card
          ? [result.card.snapshot_id]
          : [];
      if (
        project &&
        !result.comparison_pending &&
        !result.candidates.length &&
        result.comparison_selections.every((s) => s.status === "resolved") &&
        JSON.stringify(ids) !== JSON.stringify(project.snapshot_ids)
      ) {
        const updated = await post<Project>(
          `/api/projects/${project.project_id}/commands`,
          { action: "capture_selection", expected_revision: project.revision },
        );
        rememberProject(updated);
        await refreshProjects();
      } else if (!project)
        setShortlistState((old) => old.filter((id) => ids.includes(id)));
    });
  }
  async function ask(question: string) {
    if (!project || view !== "project") return send({ question });
    await perform(async () => {
      const version = ++requestVersion.current;
      setMessages((old) => [...old, { role: "user", text: question }]);
      const result = await post<{
        answer: string;
        status: string;
        project?: Project;
        evidence: Evidence[];
        claims: { evidence_ids: string[] }[];
        review?: ReviewContext | null;
      }>(`/api/projects/${project.project_id}/ask`, {
        question,
        expected_revision: project.revision,
      });
      if (version !== requestVersion.current) return;
      if (result.project) rememberProject(result.project);
      if (result.review !== undefined)
        setData((old) => (old ? { ...old, review: result.review } : old));
      const available = new Set(result.evidence.map((e) => e.evidence_id));
      if (
        result.claims.some((c) =>
          c.evidence_ids.some((id) => !available.has(id)),
        )
      )
        throw new Error("Источники ответа не подтверждены.");
      setMessages((old) => [
        ...old,
        { role: "assistant", text: result.answer, evidence: result.evidence },
      ]);
    });
  }
  async function reset() {
    await perform(async () => {
      ++requestVersion.current;
      // Сохранённый проект остаётся; новая проверка получает отдельную сессию.
      if (session && !project)
        await api(`/api/sessions/${session}`, { method: "DELETE" });
      saveSession(
        (await post<{ session_id: string }>("/api/sessions", {})).session_id,
      );
      rememberProject(null);
      setData(null);
      setMessages([]);
      setView("comparison");
    });
  }
  async function openProject(id: string) {
    await perform(async () => {
      const version = ++requestVersion.current;
      const result = await post<{ project: Project; response: ChatResponse }>(
        `/api/projects/${id}/open`,
        {},
      );
      if (version !== requestVersion.current) return;
      rememberProject(result.project);
      saveSession(result.project.session_id);
      restoreAnswer(result.response, true);
      setView("project");
    });
  }
  async function createProject(title: string, goal: string) {
    return perform(async () => {
      const created = await post<Project>("/api/projects", {
        session_id: session,
        title,
        goal,
      });
      let updated = created;
      if (shortlist.length)
        updated = await post<Project>(
          `/api/projects/${created.project_id}/commands`,
          {
            action: "set_shortlist",
            expected_revision: created.revision,
            snapshot_ids: shortlist,
          },
        );
      rememberProject(updated);
      saveSession(updated.session_id);
      setView("project");
      setMessages([]);
      await refreshProjects();
    });
  }
  async function command(action: string, values: Record<string, unknown> = {}) {
    if (!project) return;
    await perform(async () => {
      const updated = await post<Project>(
        `/api/projects/${project.project_id}/commands`,
        { action, expected_revision: project.revision, ...values },
      );
      rememberProject(updated);
      await refreshProjects();
    });
  }
  const setShortlist = (ids: string[]) =>
    project
      ? void command("set_shortlist", { snapshot_ids: ids })
      : setShortlistState(ids);
  async function upload(file: File) {
    if (!project) return;
    await perform(async () => {
      if (file.size > 2 * 1024 * 1024)
        throw new Error("Документ превышает 2 МБ.");
      const updated = await api<Project>(
        `/api/projects/${project.project_id}/documents?name=${encodeURIComponent(file.name)}&expected_revision=${project.revision}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: file,
        },
      );
      rememberProject(updated);
      await refreshProjects();
    });
  }
  return {
    data,
    health,
    messages,
    busy,
    error,
    shortlist,
    project,
    projects,
    view,
    setView,
    setShortlist,
    send,
    ask,
    reset,
    openProject,
    createProject,
    command,
    upload,
  };
}
