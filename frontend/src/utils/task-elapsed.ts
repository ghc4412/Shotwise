import type { TaskItem } from "@/types";
import { parseIso } from "@/utils/date-format";

export interface TaskElapsed {
  waitingSeconds: number;
  runningSeconds: number | null;
  totalSeconds: number;
}

function parseTimestamp(value: string | null): number | null {
  if (!value) return null;
  // 复用 parseIso：后端 dt_to_iso 直出 DB 里的 naive UTC 串（无 Z / 偏移量），直接交给
  // Date.parse 会按本地时区解释，与进行中任务的末端（Date.now 的 UTC epoch）相差一个
  // 时区偏移，时长因此多算整个时差。终态任务两端同为 naive、差值相消，所以该问题只在
  // 进行中任务（finished_at 为空）上暴露。
  const timestamp = parseIso(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

function nonNegativeSeconds(start: number | null, end: number | null): number {
  if (start === null || end === null) return 0;
  return Math.max(0, Math.floor((end - start) / 1000));
}

export function formatElapsedDuration(seconds: number): string {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainder = safeSeconds % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

export function formatTaskElapsed(task: Pick<TaskItem, "queued_at" | "started_at" | "finished_at">, nowMs: number): TaskElapsed {
  const queuedAt = parseTimestamp(task.queued_at);
  const startedAt = parseTimestamp(task.started_at);
  const finishedAt = parseTimestamp(task.finished_at) ?? (Number.isFinite(nowMs) ? nowMs : Date.now());
  const waitingSeconds = nonNegativeSeconds(queuedAt, startedAt ?? finishedAt);
  const runningSeconds = startedAt === null ? null : nonNegativeSeconds(startedAt, finishedAt);
  return {
    waitingSeconds,
    runningSeconds,
    totalSeconds: nonNegativeSeconds(queuedAt, finishedAt),
  };
}
