import { describe, expect, it } from "vitest";
import { formatTaskElapsed, formatElapsedDuration } from "./task-elapsed";
import type { TaskItem } from "@/types";

const baseTask: TaskItem = {
  task_id: "task-1",
  project_name: "demo",
  task_type: "video",
  media_type: "video",
  resource_id: "S01",
  resource_type: null,
  script_file: null,
  payload: {},
  status: "running",
  result: null,
  error_message: null,
  cancelled_by: null,
  provider_id: null,
  provider_job_id: null,
  source: "webui",
  queued_at: "2026-08-31T00:00:00.000Z",
  started_at: "2026-08-31T00:00:10.000Z",
  finished_at: null,
  updated_at: "2026-08-31T00:00:10.000Z",
};

describe("formatElapsedDuration", () => {
  it("formats seconds below one minute", () => {
    expect(formatElapsedDuration(9)).toBe("00:09");
  });

  it("formats minutes and hours without losing seconds", () => {
    expect(formatElapsedDuration(3723)).toBe("01:02:03");
  });

  it("clamps invalid and negative durations", () => {
    expect(formatElapsedDuration(-1)).toBe("00:00");
    expect(formatElapsedDuration(Number.NaN)).toBe("00:00");
  });
});

describe("formatTaskElapsed", () => {
  it("reports queue wait and running durations for an active task", () => {
    expect(formatTaskElapsed(baseTask, Date.parse("2026-08-31T00:01:15.000Z"))).toEqual({
      waitingSeconds: 10,
      runningSeconds: 65,
      totalSeconds: 75,
    });
  });

  it("uses finished_at as the stable end for terminal tasks", () => {
    const task: TaskItem = {
      ...baseTask,
      status: "succeeded",
      finished_at: "2026-08-31T00:01:00.000Z",
    };
    expect(formatTaskElapsed(task, Date.parse("2026-08-31T01:00:00.000Z"))).toEqual({
      waitingSeconds: 10,
      runningSeconds: 50,
      totalSeconds: 60,
    });
  });

  it("does not invent running time before a task starts", () => {
    const task: TaskItem = { ...baseTask, status: "queued", started_at: null };
    expect(formatTaskElapsed(task, Date.parse("2026-08-31T00:00:12.000Z"))).toEqual({
      waitingSeconds: 12,
      runningSeconds: null,
      totalSeconds: 12,
    });
  });
});
