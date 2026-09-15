export type MemoryScope = "user" | "project";

export type MemoryCategory =
  | "preference"
  | "style"
  | "world"
  | "terminology"
  | "workflow"
  | "other";

export interface MemoryEntry {
  id: string;
  user_id: string;
  scope: MemoryScope;
  project_name: string | null;
  category: MemoryCategory;
  content: string;
  source: string;
  confirmed: boolean;
  source_session_id: string | null;
  source_message_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MemoryCandidate extends MemoryEntry {
  status: "pending" | "accepted" | "rejected";
}

export interface MemoryListResponse<T = MemoryEntry> {
  items: T[];
}

export interface CreateMemoryRequest {
  category: MemoryCategory;
  content: string;
  source?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateMemoryRequest {
  category?: MemoryCategory;
  content?: string;
  metadata?: Record<string, unknown>;
}

export interface MemoryExport {
  format: "shotwise-agent-memory";
  version: number;
  user_memories: MemoryEntry[];
  project_memories: MemoryEntry[];
}
