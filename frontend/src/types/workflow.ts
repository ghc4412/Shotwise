export type WorkflowRunStatus =
  | "planned"
  | "running"
  | "paused"
  | "waiting_review"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface WorkflowNodeRun {
  id: string;
  node_key: string;
  attempt_no: number;
  status: string;
  progress: number | null;
  progress_source: string | null;
  phase_code: string | null;
  error_code: string | null;
  fencing_token: number;
}

export interface WorkflowRunSummary {
  id: string;
  workflow_revision_id: string;
  status: WorkflowRunStatus;
  mode: "auto" | "manual" | "hybrid";
  progress: number | null;
  version: number;
  control_generation: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface WorkflowRunDetail extends WorkflowRunSummary {
  workspace_id: string;
  project_id: string;
  input_fingerprint: string;
  nodes: WorkflowNodeRun[];
}

export interface WorkflowEvent {
  seq: number;
  event_id: string;
  aggregate_type: string;
  aggregate_id: string;
  aggregate_version: number;
  event_type: string;
  event_version: number;
  payload: Record<string, unknown>;
  trace_id: string | null;
  created_at: string;
}
