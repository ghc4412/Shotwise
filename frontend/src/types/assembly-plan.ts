/**
 * Phase 2A assembly-plan contracts.
 *
 * These shapes mirror the deterministic media-assembly API. Rendering and media
 * processing remain backend concerns; the UI only presents the saved plan and
 * its current revision.
 */

export type AssemblyPlanScope = "episode" | "project" | "selection";

export type AssemblyPlanStatus =
  | "draft"
  | "confirmed"
  | "preview_pending"
  | "preview_ready"
  | "render_pending"
  | "rendering"
  | "completed"
  | "stale"
  | "failed";

export type AssemblyIssueSeverity = "info" | "warning" | "error";

export interface AssemblyPlanIssue {
  path?: string;
  code: string;
  message: string;
  severity?: AssemblyIssueSeverity;
  item_id?: string | null;
  source_id?: string | null;
  details?: Record<string, unknown>;
}

/** The validation payload currently returned by the backend. */
export interface AssemblyValidation {
  valid: boolean;
  errors: AssemblyPlanIssue[];
  warnings: AssemblyPlanIssue[];
  checked_at?: string | null;
}

/** A timeline item in an immutable assembly-plan revision. */
export type AssemblyItemStatus = "ready" | "missing" | "stale" | "failed";

export interface AssemblyTimelineItem {
  id: string;
  order: number;
  kind: string;
  source_ref: string;
  duration_seconds: number;
  trim_start_seconds?: number;
  trim_end_seconds?: number;
  transition?: string | null;
  label?: string | null;
  media_ref?: string | null;
  thumbnail_url?: string | null;
  source_id?: string | null;
  episode?: number | null;
  scene_id?: string | null;
  status?: AssemblyItemStatus;
  source_revision?: string | number | null;
}

export type AssemblyAudioStrategy = "keep" | "duck" | "mute";
export type AssemblySubtitleMode = "srt" | "vtt" | "burn-in";

export type AssemblyRenderJobStatus = "queued" | "running" | "succeeded" | "failed";

export interface AssemblyRenderJob {
  id: string;
  plan_id: string;
  project_name?: string | null;
  revision_number: number;
  kind: "preview" | "final";
  status: AssemblyRenderJobStatus;
  attempt?: number | null;
  max_attempts?: number | null;
  input_fingerprint?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
  artifact?: AssemblyRenderArtifact | null;
}

export interface CreateAssemblyFinalRenderRequest {
  revision_number: number;
  max_attempts?: number;
}

export interface CreateAssemblyPreviewRenderRequest {
  revision_number?: number;
  max_attempts?: number;
}

export interface AssemblyRenderArtifact {
  id: string;
  kind?: string;
  url?: string | null;
  download_url?: string | null;
  content_url?: string | null;
  mime_type?: string | null;
  revision_number?: number | null;
  duration_seconds?: number | null;
  created_at?: string | null;
}

export type AssemblyFinalReviewFramePosition = "first" | "middle" | "last";

export interface AssemblyFinalReviewFrame {
  position: AssemblyFinalReviewFramePosition;
  timestamp_seconds: number;
  relative_path: string;
}

export interface AssemblyFinalReviewChecks {
  duration: {
    seconds: number;
    metadata_seconds?: number | null;
    within_metadata_tolerance: boolean;
  };
  audio_stream: {
    present: boolean;
  };
  black_frames: {
    detected: boolean;
    segments: Array<{
      start_seconds: number;
      end_seconds: number;
      duration_seconds: number;
      edge?: "opening" | "ending" | "middle" | "full";
    }>;
  };
  timeline_duration?: {
    expected_seconds: number;
    actual_seconds: number;
    within_tolerance: boolean;
  };
  audio_quality?: {
    stream_present: boolean;
    silence_segments: Array<{
      start_seconds?: number | null;
      end_seconds?: number | null;
      duration_seconds?: number | null;
    }>;
    abnormal: boolean;
    severity: "info" | "warning" | "blocking" | null;
  };
  subtitle_bounds?: {
    detected: boolean;
    valid: boolean;
    cue_count: number;
    items: Array<Record<string, unknown>>;
  };
  frames: Array<AssemblyFinalReviewFrame & { available?: boolean; error_code?: string }>;
}

export interface AssemblyFinalReviewSnapshot {
  id: string;
  artifact_id: string;
  plan_id: string;
  revision_number: number;
  status: "ready" | "blocked";
  created_at: string;
  confirmed_by?: string | null;
  confirmed_at?: string | null;
}

export interface AssemblyFinalReview {
  status: "ready" | "blocked";
  plan_id: string;
  revision_number: number;
  artifact: AssemblyRenderArtifact;
  checks: AssemblyFinalReviewChecks;
  blocking_reasons?: string[];
  review_snapshot?: AssemblyFinalReviewSnapshot;
}

export type ConfirmAssemblyFinalReviewResponse = AssemblyFinalReviewSnapshot;

export interface ConfirmAssemblyFinalReviewRequest {
  revision_number: number;
}

export interface AssemblyPackagingTextConfig {
  text: string;
  duration_seconds: number;
}

export interface AssemblyPackagingCoverConfig {
  source_ref: string;
  duration_seconds: number;
  fit?: "cover" | "contain";
}

export interface AssemblyPackagingConfig {
  intro?: AssemblyPackagingTextConfig;
  outro?: AssemblyPackagingTextConfig;
  cover?: AssemblyPackagingCoverConfig;
  [key: string]: unknown;
}

export interface AssemblyDocument {
  source_snapshot: Record<string, unknown>;
  timeline: AssemblyTimelineItem[];
  audio: Record<string, unknown>;
  subtitle: Record<string, unknown>;
  packaging: AssemblyPackagingConfig;
  output_profile: Record<string, unknown>;
}

export interface AssemblyPlanRevision extends AssemblyDocument {
  id: string;
  plan_id: string;
  version_number: number;
  source_fingerprint: string;
  validation: AssemblyValidation;
  created_by: string;
  created_at: string;
}

export interface AssemblyPlan {
  id: string;
  user_id?: string;
  project_name: string;
  scope: AssemblyPlanScope;
  episode_number: number | null;
  name: string;
  status: AssemblyPlanStatus;
  current_revision_number: number;
  current_source_fingerprint: string;
  created_at: string;
  updated_at: string;
  current_revision?: AssemblyPlanRevision;
  stale?: boolean;
  preview_artifact?: AssemblyRenderArtifact | null;
  preview_revision_number?: number | null;
  preview_ready_at?: string | null;
  /** Supported by the dedicated preview-confirm contract when available. */
  preview_confirmed_by?: string | null;
  preview_confirmed_at?: string | null;
  /** Current backend names for the explicit final-render confirmation. */
  render_confirmed_by?: string | null;
  render_confirmed_at?: string | null;
}

export type AssemblyPlanListResponse = { items: AssemblyPlan[] };
export type AssemblyPlanResponse = AssemblyPlan;

export interface CreateAssemblyPlanRequest extends AssemblyDocument {
  name: string;
  scope?: AssemblyPlanScope;
  episode_number?: number | null;
}

export type CreateAssemblyPlanRevisionRequest = AssemblyDocument;

export interface ConfirmAssemblyPlanPreviewRequest {
  revision_number: number;
}

export type ConfirmAssemblyPlanPreviewResponse = AssemblyPlanResponse;

export interface TransitionAssemblyPlanRequest {
  status: AssemblyPlanStatus;
}

export interface CheckAssemblyPlanStaleRequest {
  source_snapshot: Record<string, unknown>;
}

/** UI-only normalized view used by future timeline editing work. */
export interface AssemblyPlanScopeInfo {
  type: AssemblyPlanScope;
  episode?: number | null;
  item_ids?: string[];
}

export interface AssemblyPlanView {
  id: string;
  project_name: string;
  scope: AssemblyPlanScopeInfo;
  status: AssemblyPlanStatus;
  revision: number;
  source_fingerprint?: string | null;
  current_source_fingerprint?: string | null;
  stale: boolean;
  items: AssemblyTimelineItem[];
  validation: AssemblyValidation;
  created_at?: string | null;
  updated_at?: string | null;
}
