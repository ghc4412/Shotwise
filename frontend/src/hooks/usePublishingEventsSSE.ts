import { useEffect, useRef } from "react";
import { API } from "@/api";
import type { ProjectChangeBatchPayload } from "@/types";
import type { SseConnection } from "@/utils/sse";

/** Subscribe to publish-job refresh signals without affecting workspace state. */
export function usePublishingEventsSSE(
  projectName: string | null | undefined,
  onJobUpdated: (jobId: string) => void,
): void {
  const callbackRef = useRef(onJobUpdated);
  useEffect(() => {
    callbackRef.current = onJobUpdated;
  }, [onJobUpdated]);

  useEffect(() => {
    if (!projectName) return;
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let source: SseConnection | null = null;

    const connect = () => {
      if (disposed) return;
      source?.close();
      source = API.openProjectEventStream({
        projectName,
        onChanges(payload: ProjectChangeBatchPayload) {
          if (disposed) return;
          const jobIds = new Set(
            payload.changes
              .filter((change) => change.entity_type === "publish_job" && change.action === "publish_job_updated")
              .map((change) => change.entity_id),
          );
          for (const jobId of jobIds) callbackRef.current(jobId);
        },
        onError() {
          if (disposed || reconnectTimer) return;
          reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connect();
          }, 3000);
        },
      });
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      source?.close();
      source = null;
    };
  }, [projectName]);
}
