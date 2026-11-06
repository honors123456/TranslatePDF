const SESSION_KEY = "tpdf-task-session";
const TASK_ID = /^[a-f0-9]{12}$/;

export function readTaskSession(search: string): { ids: string[]; currentId: string | null } {
  let ids: string[] = [];
  let currentId: string | null = null;
  try {
    const saved = JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? "null");
    if (Array.isArray(saved?.ids)) {
      ids = saved.ids.filter((id: unknown): id is string => typeof id === "string" && TASK_ID.test(id));
    }
    if (typeof saved?.currentId === "string" && TASK_ID.test(saved.currentId)) currentId = saved.currentId;
  } catch {}
  const requested = new URLSearchParams(search).get("task");
  if (requested && TASK_ID.test(requested)) currentId = requested;
  if (currentId) ids.unshift(currentId);
  return { ids: [...new Set(ids)], currentId };
}

export function saveTaskSession(ids: string[], currentId: string | null) {
  try { sessionStorage.setItem(SESSION_KEY, JSON.stringify({ ids, currentId })); } catch {}
  const url = new URL(window.location.href);
  if (currentId) url.searchParams.set("task", currentId);
  else url.searchParams.delete("task");
  if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url);
}
