import { useCallback, useEffect, useRef, useState } from "react";
import { API } from "@/api";
import type { DurableBatchResponse } from "@/types/batch";

const STORAGE_PREFIX = "shotwise-durable-batches:";
const MAX_TRACKED_BATCHES = 12;
const ACTIVE_POLL_MS = 2500;
const IDLE_POLL_MS = 15000;
const REGISTERED_EVENT = "shotwise:durable-batch-registered";

interface TrackedBatch {
  batchId: string;
  registeredAt: number;
}

function storageKey(projectName: string): string {
  return STORAGE_PREFIX + encodeURIComponent(projectName);
}

function isTrackedBatch(value: unknown): value is TrackedBatch {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<TrackedBatch>;
  return (
    typeof candidate.batchId === "string" &&
    candidate.batchId.length > 0 &&
    typeof candidate.registeredAt === "number"
  );
}

function readTrackedBatches(projectName: string): TrackedBatch[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(storageKey(projectName));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isTrackedBatch).slice(0, MAX_TRACKED_BATCHES);
  } catch {
    return [];
  }
}

function writeTrackedBatches(projectName: string, batches: TrackedBatch[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(projectName), JSON.stringify(batches));
  } catch {
    // Local persistence is optional; the in-memory response remains usable.
  }
}

/** Register a createBatch response so the HUD can recover it after a reload. */
export function registerDurableBatch(projectName: string, batchId: string): void {
  if (!projectName || !batchId) return;
  const batches = readTrackedBatches(projectName).filter((item) => item.batchId !== batchId);
  batches.unshift({ batchId, registeredAt: Date.now() });
  writeTrackedBatches(projectName, batches.slice(0, MAX_TRACKED_BATCHES));
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(REGISTERED_EVENT, { detail: { projectName } }));
  }
}

function isActive(status: DurableBatchResponse["status"]): boolean {
  return status === "admitted" || status === "running";
}

export function useDurableBatches(projectName: string | null) {
  const [batches, setBatches] = useState<DurableBatchResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [loadedProjectName, setLoadedProjectName] = useState<string | null>(null);
  const requestVersion = useRef(0);

  const refresh = useCallback(async () => {
    if (!projectName) {
      return;
    }

    const tracked = readTrackedBatches(projectName);
    if (tracked.length === 0) {
      setLoadedProjectName(projectName);
      setLoading(false);
      setError(null);
      return;
    }

    const version = ++requestVersion.current;
    setRefreshing(true);
    try {
      const results = await Promise.allSettled(
        tracked.map((item) => API.getBatch(projectName, item.batchId)),
      );
      if (version !== requestVersion.current) return;

      const next: DurableBatchResponse[] = [];
      let firstError: unknown = null;
      for (const result of results) {
        if (result.status === "fulfilled") {
          next.push(result.value);
        } else if (!firstError) {
          firstError = result.reason;
        }
      }
      setLoadedProjectName(projectName);
      setBatches(next);
      setError(firstError);
    } finally {
      if (version === requestVersion.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [projectName]);

  useEffect(() => {
    requestVersion.current += 1;
    if (!projectName) return;
    const initialRefresh = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(initialRefresh);
  }, [projectName, refresh]);

  useEffect(() => {
    if (!projectName || typeof window === "undefined") return;
    const onRegistered = (event: Event) => {
      const detail = (event as CustomEvent<{ projectName?: string }>).detail;
      if (detail?.projectName === projectName) void refresh();
    };
    window.addEventListener(REGISTERED_EVENT, onRegistered);
    return () => window.removeEventListener(REGISTERED_EVENT, onRegistered);
  }, [projectName, refresh]);

  const hasActiveBatches = batches.some((batch) => isActive(batch.status));
  const isCurrentProjectLoaded = loadedProjectName === projectName;

  useEffect(() => {
    if (!projectName) return;
    const interval = window.setInterval(
      () => void refresh(),
      hasActiveBatches ? ACTIVE_POLL_MS : IDLE_POLL_MS,
    );
    return () => window.clearInterval(interval);
  }, [hasActiveBatches, projectName, refresh]);

  const cancel = useCallback(
    async (batchId: string) => {
      if (!projectName) return;
      const response = await API.cancelBatch(projectName, batchId);
      setBatches((current) => [response, ...current.filter((batch) => batch.batch_id !== batchId)]);
    },
    [projectName],
  );

  const retryFailed = useCallback(
    async (batchId: string) => {
      if (!projectName) return;
      const response = await API.retryFailedBatch(projectName, batchId);
      registerDurableBatch(projectName, batchId);
      setBatches((current) => [response, ...current.filter((batch) => batch.batch_id !== batchId)]);
    },
    [projectName],
  );

  return {
    batches: isCurrentProjectLoaded ? batches : [],
    loading: Boolean(projectName) && (loading || !isCurrentProjectLoaded),
    refreshing,
    error: isCurrentProjectLoaded ? error : null,
    hasActiveBatches,
    refresh,
    cancel,
    retryFailed,
  };
}
