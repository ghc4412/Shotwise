import { getAuthHeader } from "@/utils/auth";

export interface PublishingPlatform {
  platform: string;
  display_name: string;
  adapter_connected: boolean;
  supports_oauth: boolean;
  supports_publish: boolean;
  supports_schedule: boolean;
  supports_status_polling: boolean;
  supports_retract: boolean;
  supports_cover_update: boolean;
  unavailable_reason?: string | null;
}

export interface PublishingAccount {
  id: string;
  platform: string;
  platform_account_id: string;
  account_name: string;
  avatar_url?: string | null;
  scopes: string[];
  status: string;
  token_expires_at?: string | null;
}

export interface PublishJob {
  id: string;
  artifact_id: string;
  review_snapshot_id: string;
  project_name?: string | null;
  account_id?: string | null;
  platform: string;
  status: string;
  attempt: number;
  max_attempts: number;
  error_code?: string | null;
  error_message?: string | null;
  external_content_id?: string | null;
  external_status?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
}

export interface PublishJobListResponse {
  items: PublishJob[];
  total: number;
  limit: number;
  offset: number;
}

const API_BASE = "/api/v1";

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const authorization = getAuthHeader();
  if (authorization) headers.set("Authorization", authorization);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const detail = payload && typeof payload === "object" && "detail" in payload
      ? payload.detail
      : undefined;
    const code = typeof detail === "string"
      ? detail
      : detail && typeof detail === "object" && "code" in detail
        ? String(detail.code)
        : response.statusText;
    throw new Error(code || `HTTP ${response.status}`);
  }
  const body: unknown = await response.json();
  return body as T;
}

export const publishingApi = {
  listPlatforms(): Promise<PublishingPlatform[]> {
    return request("/publishing/platforms");
  },
  listAccounts(): Promise<PublishingAccount[]> {
    return request("/publishing/accounts");
  },
  listJobs(limit = 20, offset = 0): Promise<PublishJobListResponse> {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    return request(`/publish-jobs?${params.toString()}`);
  },
  getJob(jobId: string): Promise<PublishJob> {
    return request(`/publish-jobs/${encodeURIComponent(jobId)}`);
  },
  createJob(artifactId: string, body: {
    review_snapshot_id: string;
    platform: string;
    idempotency_key: string;
    account_id?: string;
    destination?: Record<string, unknown>;
  }): Promise<PublishJob> {
    return request(`/render-artifacts/${encodeURIComponent(artifactId)}/publish`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  retryJob(jobId: string): Promise<PublishJob> {
    return request(`/publish-jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
  },
  cancelJob(jobId: string): Promise<PublishJob> {
    return request(`/publish-jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  },
  pollJob(jobId: string): Promise<PublishJob> {
    return request(`/publish-jobs/${encodeURIComponent(jobId)}/poll`, { method: "POST" });
  },
  retractJob(jobId: string): Promise<PublishJob> {
    return request(`/publish-jobs/${encodeURIComponent(jobId)}/retract`, { method: "POST" });
  },
};





