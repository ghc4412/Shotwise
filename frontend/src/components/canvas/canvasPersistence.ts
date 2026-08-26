import { useCallback, useEffect, useRef, useState } from "react";

export type CanvasPersistenceStatus = "clean" | "dirty" | "saving" | "saved" | "error";
export type CanvasSaveShortcutEvent = Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "preventDefault">;

export function handleCanvasSaveShortcut(
  event: CanvasSaveShortcutEvent,
  save: () => Promise<unknown> | void,
): boolean {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    void save();
    return true;
  }
  return false;
}

export interface CanvasPersistenceController<T> {
  getStatus(): CanvasPersistenceStatus;
  setBaseline(snapshot: T): void;
  markDirty(snapshot: T): void;
  saveNow(): Promise<boolean>;
  retry(): Promise<boolean>;
  updateSave(save: (snapshot: T, previousSnapshot: T | undefined) => Promise<T | void>): void;
  dispose(): void;
}

export interface CanvasPersistenceControllerOptions<T> {
  save: (snapshot: T, previousSnapshot: T | undefined) => Promise<T | void>;
  debounceMs?: number;
  onStatusChange?: (status: CanvasPersistenceStatus) => void;
}

export interface UseCanvasPersistenceOptions<T> {
  snapshot: T;
  snapshotKey: string;
  save: (snapshot: T, previousSnapshot: T | undefined) => Promise<T | void>;
  hydrated?: boolean;
  enabled?: boolean;
  debounceMs?: number;
}

export interface UseCanvasPersistenceResult {
  status: CanvasPersistenceStatus;
  saveNow: () => Promise<boolean>;
  retry: () => Promise<boolean>;
  reset: (snapshot: unknown, snapshotKey?: string) => void;
}

export function createCanvasPersistenceController<T>({
  save: initialSave,
  debounceMs = 1_000,
  onStatusChange,
}: CanvasPersistenceControllerOptions<T>): CanvasPersistenceController<T> {
  let save = initialSave;
  let latestSnapshot: T | undefined;
  let persistedSnapshot: T | undefined;
  let generation = 0;
  let persistedGeneration = 0;
  let status: CanvasPersistenceStatus = "clean";
  let timer: ReturnType<typeof setTimeout> | undefined;
  let flight: Promise<boolean> | undefined;
  let disposed = false;
  let baselineEpoch = 0;

  const emit = (next: CanvasPersistenceStatus) => {
    if (disposed || status === next) return;
    status = next;
    onStatusChange?.(next);
  };

  const schedule = () => {
    if (disposed || flight || generation === persistedGeneration) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = undefined;
      void saveNow();
    }, debounceMs);
  };

  const flush = async (): Promise<boolean> => {
    while (!disposed && latestSnapshot !== undefined && generation !== persistedGeneration) {
      const targetGeneration = generation;
      const targetSnapshot = latestSnapshot;
      const targetBaselineEpoch = baselineEpoch;
      emit("saving");

      try {
        const savedSnapshot = await save(targetSnapshot, persistedSnapshot);
        if (disposed || targetBaselineEpoch !== baselineEpoch) return false;
        persistedSnapshot = savedSnapshot ?? targetSnapshot;
      } catch {
        if (disposed || targetBaselineEpoch !== baselineEpoch) return false;
        if (generation === targetGeneration) {
          emit("error");
        } else {
          emit("dirty");
          schedule();
        }
        return false;
      }

      if (disposed || targetBaselineEpoch !== baselineEpoch) return false;
      if (generation === targetGeneration) {
        persistedGeneration = targetGeneration;
        emit("saved");
        return true;
      }

      emit("dirty");
    }

    return !disposed;
  };

  const saveNow = (): Promise<boolean> => {
    if (disposed) return Promise.resolve(false);
    if (timer) {
      clearTimeout(timer);
      timer = undefined;
    }
    if (flight) return flight;

    flight = flush().finally(() => {
      flight = undefined;
      if (!disposed && generation !== persistedGeneration && status !== "error") schedule();
    });
    return flight;
  };

  return {
    getStatus: () => status,
    setBaseline: (snapshot) => {
      if (disposed) return;
      baselineEpoch += 1;
      latestSnapshot = snapshot;
      persistedSnapshot = snapshot;
      generation += 1;
      persistedGeneration = generation;
      if (timer) {
        clearTimeout(timer);
        timer = undefined;
      }
      emit("clean");
    },
    markDirty: (snapshot) => {
      if (disposed) return;
      latestSnapshot = snapshot;
      generation += 1;
      emit("dirty");
      schedule();
    },
    saveNow,
    retry: saveNow,
    updateSave: (nextSave) => {
      save = nextSave;
    },
    dispose: () => {
      baselineEpoch += 1;
      disposed = true;
      if (timer) clearTimeout(timer);
      timer = undefined;
      latestSnapshot = undefined;
    },
  };
}

export function useCanvasPersistence<T>({
  snapshot,
  snapshotKey,
  save,
  hydrated = true,
  enabled = true,
  debounceMs = 1_000,
}: UseCanvasPersistenceOptions<T>): UseCanvasPersistenceResult {
  const [, rerender] = useState(0);
  const [controller] = useState<CanvasPersistenceController<T>>(() =>
    createCanvasPersistenceController({
      save,
      debounceMs,
      onStatusChange: () => rerender((value) => value + 1),
    }),
  );
  const baselineKeyRef = useRef<string | undefined>(undefined);
  const hasBaselineRef = useRef(false);

  useEffect(() => {
    controller.updateSave(save);
  }, [controller, save]);

  useEffect(() => {
    if (!enabled || !hydrated) {
      hasBaselineRef.current = false;
      baselineKeyRef.current = undefined;
      return;
    }
    if (!hasBaselineRef.current) {
      hasBaselineRef.current = true;
      baselineKeyRef.current = snapshotKey;
      controller.setBaseline(snapshot);
      return;
    }
    if (baselineKeyRef.current === snapshotKey) return;
    baselineKeyRef.current = snapshotKey;
    controller.markDirty(snapshot);
  }, [controller, enabled, hydrated, snapshot, snapshotKey]);

  useEffect(() => () => controller.dispose(), [controller]);

  const saveNow = useCallback(() => controller.saveNow(), [controller]);
  const retry = useCallback(() => controller.retry(), [controller]);
  const reset = useCallback((nextSnapshot: unknown, nextSnapshotKey?: string) => {
    hasBaselineRef.current = true;
    baselineKeyRef.current = nextSnapshotKey;
    controller.setBaseline(nextSnapshot as T);
  }, [controller]);
  return { status: controller.getStatus(), saveNow, retry, reset };
}
