/**
 * Durable generation batch API contracts.
 *
 * Mirrors the request models and response projection in
 * server/routers/batches.py.
 */

import type { TaskStatus } from "./task";

export type DurableBatchStatus =
  | "admitted"
  | "running"
  | "succeeded"
  | "partially_succeeded"
  | "failed"
  | "cancelled";

export type DurableBatchSource = "webui" | "agent" | "api";

export interface DurableBatchTaskRequest {
  task_type: string;
  media_type: string;
  resource_id: string;
  payload?: Record<string, unknown> | null;
  script_file?: string | null;
  resource_type?: string | null;
  source?: DurableBatchSource;
  dependency_task_id?: string | null;
  dependency_group?: string | null;
  dependency_index?: number | null;
  provider_id?: string | null;
}

export interface DurableBatchItemRequest {
  item_id: string;
  task: DurableBatchTaskRequest;
}

export interface CreateDurableBatchRequest {
  items: DurableBatchItemRequest[];
}

export interface DurableBatchTaskSummary {
  item_id: string;
  task_id: string;
  status: TaskStatus;
}

export interface DurableBatchResponse {
  batch_id: string;
  project_name: string;
  status: DurableBatchStatus;
  cancel_requested: boolean;
  tasks: DurableBatchTaskSummary[];
}
