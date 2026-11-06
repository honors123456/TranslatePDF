"use client";

import Link from "next/link";
import { readTaskSession, saveTaskSession } from "@/lib/task-session";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  TaskSnapshot,
  cancelTask,
  createTask,
  downloadUrl,
  eventsUrl,
  API_BASE,
  previewUrl,
} from "@/lib/api";
import {
  Settings,
  defaultSettings,
  engineConfigFrom,
  loadSettings,
} from "@/lib/settings";

const STATUS_LABELS: Record<TaskSnapshot["status"], string> = {
  running: "翻译中",
  done: "完成",
  error: "失败",
  cancelled: "已取消",
};

export default function Home() {
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [tasks, setTasks] = useState<TaskSnapshot[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [pages, setPages] = useState("");
  const [notice, setNotice] = useState("");
  const [dragging, setDragging] = useState(false);
  const [reconnecting, setReconnecting] = useState<Record<string, boolean>>({});
  const [sessionLoaded, setSessionLoaded] = useState(false);
  const [originalUrls, setOriginalUrls] = useState<Record<string, string>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);
  const originalInputRef = useRef<HTMLInputElement>(null);
  const sourcesRef = useRef<Map<string, EventSource>>(new Map());
  // 原文预览用浏览器本地 objectURL，不经后端；仅本次会话有效
  const originalUrlsRef = useRef<Map<string, string>>(new Map());

  const watchTask = useCallback((id: string) => {
    sourcesRef.current.get(id)?.close();
    const source = new EventSource(eventsUrl(id));
    sourcesRef.current.set(id, source);
    source.onmessage = (msg) => {
      setReconnecting((prev) => ({ ...prev, [id]: false }));
      const snapshot: TaskSnapshot = JSON.parse(msg.data);
      setTasks((prev) => prev.map((t) => (t.id === id ? snapshot : t)));
      if (snapshot.status !== "running") {
        source.close();
        sourcesRef.current.delete(id);
      }
    };
    source.onerror = async () => {
      // 保留 EventSource 的自动重连；服务重启丢失任务时明确告知。
      setReconnecting((prev) => ({ ...prev, [id]: true }));
      try {
        const response = await fetch(`${API_BASE}/api/tasks/${id}`);
        if (sourcesRef.current.get(id) !== source) return;
        if (response.status === 404) {
          source.close();
          sourcesRef.current.delete(id);
          setTasks((prev) => prev.map((task) => task.id === id
            ? { ...task, status: "error", error: "任务已不存在，服务可能已重启或任务已过期，请重新上传。" }
            : task));
        } else if (response.ok) {
          const snapshot: TaskSnapshot = await response.json();
          if (sourcesRef.current.get(id) !== source) return;
          setTasks((prev) => prev.map((task) => task.id === id ? snapshot : task));
          if (snapshot.status !== "running") {
            source.close();
            sourcesRef.current.delete(id);
            setReconnecting((prev) => ({ ...prev, [id]: false }));
          }
        }
      } catch {
        // 网络恢复后由 EventSource 重连并获取最新快照。
      }
    };
  }, []);

  useEffect(() => {
    const sources = sourcesRef.current;
    const urls = originalUrlsRef.current;
    const timer = setTimeout(() => {
      setSettings(loadSettings());
      const saved = readTaskSession(window.location.search);
      setTasks(saved.ids.map((id) => ({
        id, filename: "正在恢复任务…", status: "running", stage: "正在连接后台任务",
        overall_progress: 0, error: null, has_mono: false, has_dual: false,
        created_at: 0, finished_at: null,
      })));
      setCurrentId(saved.currentId);
      setSessionLoaded(true);
      saved.ids.forEach(watchTask);
    }, 0);
    return () => {
      clearTimeout(timer);
      sources.forEach((source) => source.close());
      sources.clear();
      urls.forEach((url) => URL.revokeObjectURL(url));
      urls.clear();
    };
  }, [watchTask]);

  const taskIds = tasks.map((task) => task.id).join(",");
  useEffect(() => {
    if (sessionLoaded) saveTaskSession(taskIds ? taskIds.split(",") : [], currentId);
  }, [taskIds, currentId, sessionLoaded]);

  const startTranslation = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        return setNotice("只支持 PDF 文件");
      }
      const engine = engineConfigFrom(loadSettings());
      if (engine.type !== "codex" && engine.type !== "ollama" && !engine.api_key) {
        return setNotice("尚未配置 API Key，请先到「设置」填写");
      }
      setNotice("");
      try {
        const task = await createTask(
          file,
          engine,
          "en",
          loadSettings().langOut,
          pages,
        );
        const url = URL.createObjectURL(file);
        originalUrlsRef.current.set(task.id, url);
        setOriginalUrls((previous) => ({ ...previous, [task.id]: url }));
        setTasks((prev) => [task, ...prev]);
        setCurrentId(task.id);
        watchTask(task.id);
      } catch (err) {
        setNotice(`提交失败：${err instanceof Error ? err.message : err}`);
      }
    },
    [pages, watchTask],
  );

  const current = tasks.find((t) => t.id === currentId) ?? null;

  // ---------- 全屏双栏预览（翻译中/完成） ----------
  if (current) {
    const originalUrl = originalUrls[current.id];
    return (
      <div className="flex flex-col h-screen">
        <header className="flex items-center gap-4 px-4 py-2 border-b border-gray-200 dark:border-gray-700 text-sm">
          <button
            onClick={() => setCurrentId(null)}
            className="text-blue-600 hover:underline shrink-0"
          >
            ← 新任务
          </button>
          <span className="truncate font-medium">{current.filename}</span>
          <span
            className={`shrink-0 text-xs px-2 py-0.5 rounded-full ${
              current.status === "done"
                ? "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300"
                : current.status === "running"
                  ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                  : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
            }`}
          >
            {STATUS_LABELS[current.status]}
          </span>
          {current.status === "running" && (
            <div className="flex items-center gap-2 flex-1 min-w-0">
              <div className="h-1.5 flex-1 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                <div
                  className="h-full bg-blue-500 transition-all"
                  style={{ width: `${current.overall_progress}%` }}
                />
              </div>
              <span className="shrink-0 text-xs text-gray-500">
                {current.stage} {current.overall_progress}%
              </span>
              <button
                onClick={() => cancelTask(current.id)}
                className="shrink-0 text-red-500 hover:underline"
              >
                取消
              </button>
            </div>
          )}
          <div className="ml-auto flex gap-3 shrink-0">
            {current.has_dual && (
              <a
                href={downloadUrl(current.id, "dual")}
                className="text-blue-600 hover:underline"
              >
                下载双语版
              </a>
            )}
            {current.has_mono && (
              <a
                href={downloadUrl(current.id, "mono")}
                className="text-blue-600 hover:underline"
              >
                下载纯译文
              </a>
            )}
          </div>
        </header>

        <div className="flex-1 grid grid-cols-2 min-h-0">
          {/* 左栏：原文 */}
          <div className="border-r border-gray-200 dark:border-gray-700 min-h-0">
            {originalUrl ? (
              <iframe
                src={originalUrl}
                className="w-full h-full"
                title="original"
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-sm text-gray-500">
                <p>当前浏览器没有保存原文文件。</p>
                <p>重新选择本地 PDF 即可恢复左侧原文对照，不会上传或重新翻译。</p>
                <button onClick={() => originalInputRef.current?.click()}
                  className="rounded-lg border border-blue-600 px-4 py-2 text-blue-600 hover:bg-blue-50">
                  选择原文件恢复对照
                </button>
                <input ref={originalInputRef} type="file" accept=".pdf" className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (!file || !file.name.toLowerCase().endsWith(".pdf")) return;
                    const url = URL.createObjectURL(file);
                    const previous = originalUrlsRef.current.get(current.id);
                    if (previous) URL.revokeObjectURL(previous);
                    originalUrlsRef.current.set(current.id, url);
                    setOriginalUrls((urls) => ({ ...urls, [current.id]: url }));
                  }} />
              </div>
            )}
          </div>
          {/* 右栏：逐页追加已排版译文，后续页面到达时保留滚动位置。 */}
          <div className="min-h-0">
            {(current.preview_pages ?? 0) > 0 ? (
              <div className="h-full overflow-y-auto bg-gray-100 dark:bg-gray-900" aria-label="译文预览">
                <div className="sticky top-0 z-10 border-b border-gray-200 bg-white px-4 py-2 text-sm dark:border-gray-700 dark:bg-gray-800" role="status">
                  已生成 {current.preview_pages}{current.preview_total ? ` / ${current.preview_total}` : ""} 页预览
                  {current.status === "running" && "，其余页面继续后台翻译"}
                  {reconnecting[current.id] && "，进度连接中断，正在重连（显示已接收预览）"}
                  {current.status === "done" && "，完整 PDF 可在上方下载"}
                  {current.status === "cancelled" && "，任务已取消"}
                  {current.status === "error" && `，任务失败：${current.error ?? "未知错误"}`}
                </div>
                <div className="mx-auto max-w-5xl space-y-4 p-4">
                  {Array.from({ length: current.preview_pages ?? 0 }, (_, index) => (
                    <figure key={`${current.id}-${index}`}>
                      {/* 页面由后端按原比例生成，避免更新整份 PDF 重置阅读位置。 */}
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={previewUrl(current.id, index + 1)} alt={`第 ${index + 1} 页译文`}
                        loading={index === 0 ? "eager" : "lazy"} className="block h-auto w-full bg-white" />
                      <figcaption className="mt-1 text-center text-xs text-gray-500">
                        第 {index + 1} 页
                        {current.untranslated_pages?.includes(index + 1) && " · 未识别到可翻译段落，保留原页"}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              </div>
            ) : current.status === "done" && current.has_mono ? (
              <iframe
                src={downloadUrl(current.id, "mono", true)}
                className="w-full h-full"
                title="translated"
              />
            ) : current.status === "running" ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 px-10">
                <div className="w-full max-w-md h-2 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                  <div
                    className="h-full bg-blue-500 transition-all"
                    style={{ width: `${current.overall_progress}%` }}
                  />
                </div>
                <p className="text-sm text-gray-500">
                  {current.stage || "准备中"} · {current.overall_progress}%
                </p>
                <p className="text-xs text-gray-400">
                  {reconnecting[current.id] ? "无法获取最新进度，正在重连后端；恢复连接后确认后台任务状态。" : (
                    <>
                      {current.stage_total != null && current.stage_total > 0 &&
                        `当前阶段 ${current.stage_current ?? 0} / ${current.stage_total} · `}
                      {current.updated_at && `最近进度更新 ${new Date(current.updated_at * 1000).toLocaleTimeString()} · `}
                      百分比按阶段估算，不代表剩余时间
                    </>
                  )}
                </p>
                <p className="text-xs text-gray-400">
                  首个页面翻译并排版完成后，此处开始显示译文，其余页面继续后台翻译
                </p>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center px-10">
                <p className="text-sm text-red-500 break-all">
                  {current.error ?? `任务${STATUS_LABELS[current.status]}`}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ---------- 全屏上传/拖拽（空闲） ----------
  return (
    <div
      className={`flex flex-col h-screen ${dragging ? "bg-blue-50 dark:bg-gray-900" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const file = e.dataTransfer.files?.[0];
        if (file) startTranslation(file);
      }}
    >
      <header className="flex items-center justify-between px-6 py-3 border-b border-gray-200 dark:border-gray-700">
        <h1 className="text-lg font-bold">TranslationPDF</h1>
        <Link href="/settings" className="text-sm text-blue-600 hover:underline">
          设置
        </Link>
      </header>

      <main className="flex-1 flex flex-col items-center justify-center gap-6 px-6">
        <div
          onClick={() => fileInputRef.current?.click()}
          className={`w-full max-w-2xl cursor-pointer rounded-2xl border-2 border-dashed p-16 text-center transition ${
            dragging
              ? "border-blue-500 bg-blue-50 dark:bg-gray-800"
              : "border-gray-300 dark:border-gray-600 hover:border-blue-400"
          }`}
        >
          <p className="text-xl font-medium">
            拖拽 PDF 到页面任意位置，或点击选择文件
          </p>
          <p className="mt-2 text-sm text-gray-500">
            上传即开始翻译 · 引擎 {settings.engineType} · 译为{" "}
            {settings.langOut === "zh" ? "中文" : settings.langOut}
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) startTranslation(file);
            }}
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
          页码范围（可选）
          <input
            value={pages}
            onChange={(e) => setPages(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            placeholder="如 1-5，留空全文"
            className="w-40 rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-1.5"
          />
        </label>

        {notice && <p className="text-sm text-amber-600">{notice}</p>}

        {tasks.length > 0 && (
          <div className="w-full max-w-2xl space-y-1">
            <h2 className="text-sm font-medium text-gray-500">本次会话任务</h2>
            {tasks.map((task) => (
              <button
                key={task.id}
                onClick={() => setCurrentId(task.id)}
                className="flex w-full items-center justify-between rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2 text-sm hover:border-blue-400"
              >
                <span className="truncate">{task.filename}</span>
                <span className="shrink-0 text-xs text-gray-500">
                  {STATUS_LABELS[task.status]}
                  {task.status === "running" && ` ${task.overall_progress}%`}
                </span>
              </button>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
