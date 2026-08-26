import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { TaskRadar, isReviewTask, matchesRadarFilter, taskProgress } from "@/components/layout/TaskRadar";
import { useTasksStore } from "@/stores/tasks-store";
import { makeTask } from "@/test/factories";

describe("TaskRadar", () => {
  beforeEach(() => {
    useTasksStore.setState({ tasks: [], stats: { queued: 0, running: 0, cancelling: 0, succeeded: 0, failed: 0, cancelled: 0, total: 0 } });
  });

  afterEach(() => cleanup());

  it("summarizes live counts and filters the shared task store", () => {
    useTasksStore.setState({
      tasks: [
        makeTask({ task_id: "queued", status: "queued", task_type: "storyboard" }),
        makeTask({ task_id: "running", status: "running", task_type: "video" }),
        makeTask({ task_id: "review", status: "succeeded", payload: { review_status: "waiting_review" } }),
        makeTask({ task_id: "done", status: "succeeded" }),
        makeTask({ task_id: "failed", status: "failed" }),
      ],
      stats: { queued: 1, running: 1, cancelling: 0, succeeded: 3, failed: 1, cancelled: 0, total: 5 },
    });

    render(<TaskRadar />);
    fireEvent.click(screen.getByRole("button", { name: "Open task radar" }));
    expect(screen.getAllByText("Task radar")).toHaveLength(2);
    const reviewFilter = screen.getByRole("button", { name: /^Review/ });
    expect(reviewFilter).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(reviewFilter);
    expect(screen.getByText("Waiting for review")).toBeInTheDocument();
    expect(screen.queryByText("storyboard", { exact: false })).not.toBeInTheDocument();
  });

  it("normalizes progress and recognizes review tasks", () => {
    expect(taskProgress(makeTask({ status: "running", payload: { progress: 0.42 } }))).toBe(42);
    expect(taskProgress(makeTask({ status: "succeeded" }))).toBe(100);
    expect(isReviewTask(makeTask({ payload: { workflow_status: "waiting_review" } }))).toBe(true);
    expect(matchesRadarFilter(makeTask({ status: "failed" }), "failed")).toBe(true);
  });
});
