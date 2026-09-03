import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { TaskRadar, isReviewTask, matchesRadarFilter, taskProgress } from "@/components/layout/TaskRadar";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useTasksStore } from "@/stores/tasks-store";
import { makeTask } from "@/test/factories";

describe("TaskRadar", () => {
  beforeEach(() => {
    useProjectsStore.setState({ currentProjectName: null, currentProjectData: null });
    useAppStore.setState({ toast: null });
    useTasksStore.setState({ tasks: [], stats: { queued: 0, running: 0, cancelling: 0, succeeded: 0, failed: 0, cancelled: 0, total: 0 } });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

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

  it("enables stopping queued tasks for the current project and previews the cancellation", async () => {
    useProjectsStore.setState({ currentProjectName: "proj" });
    useTasksStore.setState({
      tasks: [makeTask({ project_name: "proj", status: "queued" })],
      stats: { queued: 1, running: 0, cancelling: 0, succeeded: 0, failed: 0, cancelled: 0, total: 1 },
    });
    const preview = vi.spyOn(API, "cancelAllPreview").mockResolvedValue({ queued_count: 2 });

    render(<TaskRadar />);
    fireEvent.click(screen.getByRole("button", { name: "Open task radar" }));

    const stopButton = screen.getByRole("button", { name: "停止当前项目所有排队任务" });
    expect(stopButton).toBeEnabled();
    fireEvent.click(stopButton);

    await waitFor(() => expect(preview).toHaveBeenCalledWith("proj"));
    expect(screen.getByText("确定停止当前项目的 2 个排队任务？")).toBeInTheDocument();
  });

  it("cancels the previewed queued tasks and refreshes the radar", async () => {
    useProjectsStore.setState({ currentProjectName: "proj" });
    useTasksStore.setState({
      tasks: [makeTask({ project_name: "proj", status: "queued" })],
      stats: { queued: 1, running: 0, cancelling: 0, succeeded: 0, failed: 0, cancelled: 0, total: 1 },
    });
    const cancelAll = vi.spyOn(API, "cancelAllQueued").mockResolvedValue({ cancelled_count: 1, skipped_running_count: 0 });
    const refreshTasks = vi.fn().mockResolvedValue(undefined);
    useTasksStore.setState({ refreshTasks });
    vi.spyOn(API, "cancelAllPreview").mockResolvedValue({ queued_count: 1 });

    render(<TaskRadar />);
    fireEvent.click(screen.getByRole("button", { name: "Open task radar" }));
    fireEvent.click(screen.getByRole("button", { name: "停止当前项目所有排队任务" }));
    await screen.findByText("确定停止当前项目的 1 个排队任务？");

    fireEvent.click(screen.getByRole("button", { name: "确认停止" }));

    await waitFor(() => {
      expect(cancelAll).toHaveBeenCalledWith("proj");
      expect(refreshTasks).toHaveBeenCalledTimes(1);
    });
    expect(useAppStore.getState().toast?.text).toBe("已停止 1 个排队任务");
    expect(useAppStore.getState().toast?.tone).toBe("success");
  });

  it("hides stopping when the current project has no queued tasks", () => {
    useProjectsStore.setState({ currentProjectName: "proj" });
    render(<TaskRadar />);
    fireEvent.click(screen.getByRole("button", { name: "Open task radar" }));

    expect(screen.queryByRole("button", { name: "停止当前项目所有排队任务" })).not.toBeInTheDocument();
  });
});
