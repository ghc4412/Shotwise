import { API } from "@/api";
import { registerDurableBatch } from "@/hooks/useDurableBatches";
import i18n from "@/i18n";
import { useAppStore } from "@/stores/app-store";
import { useTasksStore, type OptimisticHandle, type ResourceKind } from "@/stores/tasks-store";
import type { CreateDurableBatchRequest, DurableBatchItemRequest, DurableBatchResponse } from "@/types/batch";

export type DurableBatchKind = "storyboard" | "video" | "narration";

/** Submit a prepared batch and make it immediately visible in the task HUD. */
export async function createDurableBatch(
  projectName: string,
  kind: DurableBatchKind,
  items: DurableBatchItemRequest[],
): Promise<DurableBatchResponse | null> {
  if (items.length === 0) {
    useAppStore.getState().pushToast(i18n.t("dashboard:durable_batch_no_items"), "info");
    return null;
  }

  const payload: CreateDurableBatchRequest = { items };
  const resourceKind: ResourceKind = kind === "narration" ? "tts" : kind;
  const marks: Array<{ itemId: string; handle: OptimisticHandle }> = items.map((item) => ({
    itemId: item.item_id,
    handle: useTasksStore
      .getState()
      .beginOptimisticActive(projectName, resourceKind, item.task.resource_id, item.task.task_type),
  }));
  try {
    const response = await API.createBatch(projectName, payload);
    const results = new Map(response.tasks.map((task) => [task.item_id, task]));
    for (const mark of marks) {
      const task = results.get(mark.itemId);
      // A task id means the queue owns this item, including an already-failed
      // task that should remain visible for retry. Missing ids are rejected
      // before admission and must release the optimistic occupation.
      mark.handle.settle(task?.task_id ? [task.task_id] : []);
    }
    registerDurableBatch(projectName, response.batch_id);
    useAppStore.getState().setTaskHudOpen(true);
    useAppStore.getState().pushToast(
      i18n.t("dashboard:durable_batch_created", {
        count: items.length,
        kind: i18n.t("dashboard:durable_batch_kind_" + kind),
      }),
      "success",
    );
    return response;
  } catch (error) {
    for (const mark of marks) mark.handle.rollback();
    useAppStore.getState().pushToast(
      i18n.t("dashboard:durable_batch_create_failed", {
        message: error instanceof Error ? error.message : String(error),
      }),
      "error",
    );
    throw error;
  }
}
