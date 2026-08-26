import { afterEach, describe, expect, it, vi } from "vitest";
import { createCanvasPersistenceController, handleCanvasSaveShortcut } from "./canvasPersistence";

describe("canvas persistence controller", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces changes and saves the latest snapshot", async () => {
    vi.useFakeTimers();
    const save = vi.fn(async () => undefined);
    const controller = createCanvasPersistenceController<{ value: number }>({ save, debounceMs: 1_000 });
    controller.setBaseline({ value: 0 });
    controller.markDirty({ value: 1 });
    controller.markDirty({ value: 2 });

    await vi.advanceTimersByTimeAsync(999);
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await Promise.resolve();

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenLastCalledWith({ value: 2 }, { value: 0 });
  });

  it("saves immediately when requested manually", async () => {
    vi.useFakeTimers();
    const save = vi.fn(async () => undefined);
    const controller = createCanvasPersistenceController<{ value: number }>({ save, debounceMs: 1_000 });
    controller.setBaseline({ value: 0 });
    controller.markDirty({ value: 1 });

    await expect(controller.saveNow()).resolves.toBe(true);
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("keeps the dirty state after a failure and retries successfully", async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(undefined);
    const statuses: string[] = [];
    const controller = createCanvasPersistenceController<{ value: number }>({ save, onStatusChange: (status) => statuses.push(status) });
    controller.setBaseline({ value: 0 });
    controller.markDirty({ value: 1 });

    await expect(controller.saveNow()).resolves.toBe(false);
    expect(controller.getStatus()).toBe("error");
    await expect(controller.retry()).resolves.toBe(true);
    expect(controller.getStatus()).toBe("saved");
    expect(statuses).toEqual(["dirty", "saving", "error", "saving", "saved"]);
  });

  it("serializes saves and follows an edit made while an older request is in flight", async () => {
    let resolveFirst!: () => void;
    let resolveSecond!: () => void;
    const save = vi.fn((snapshot: { value: number }) => new Promise<void>((resolve) => {
      if (snapshot.value === 1) resolveFirst = resolve;
      else resolveSecond = resolve;
    }));
    const controller = createCanvasPersistenceController<{ value: number }>({ save });
    controller.setBaseline({ value: 0 });
    controller.markDirty({ value: 1 });
    const pending = controller.saveNow();
    controller.markDirty({ value: 2 });

    resolveFirst();
    await Promise.resolve();
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenNthCalledWith(2, { value: 2 }, { value: 1 });
    resolveSecond();
    await expect(pending).resolves.toBe(true);
    expect(controller.getStatus()).toBe("saved");
  });

  it("does not emit updates after disposal", async () => {
    let resolveSave!: () => void;
    const statuses: string[] = [];
    const controller = createCanvasPersistenceController<{ value: number }>({
      save: () => new Promise<void>((resolve) => { resolveSave = resolve; }),
      onStatusChange: (status) => statuses.push(status),
    });
    controller.setBaseline({ value: 0 });
    controller.markDirty({ value: 1 });
    const pending = controller.saveNow();
    controller.dispose();
    resolveSave();

    await expect(pending).resolves.toBe(false);
    expect(statuses).toEqual(["dirty", "saving"]);
  });

  it("handles Ctrl/Cmd+S without the browser default action", () => {
    const preventDefault = vi.fn();
    const save = vi.fn();

    expect(handleCanvasSaveShortcut({ key: "s", ctrlKey: true, metaKey: false, preventDefault }, save)).toBe(true);
    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledTimes(1);

    expect(handleCanvasSaveShortcut({ key: "x", ctrlKey: true, metaKey: false, preventDefault }, save)).toBe(false);
    expect(save).toHaveBeenCalledTimes(1);
  });
});
