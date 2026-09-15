import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublishingPage } from "./PublishingPage";
import type { PublishJob, PublishingAccount, PublishingPlatform } from "./publishing-api";

const publishingApiMock = vi.hoisted(() => ({
  listPlatforms: vi.fn(),
  listAccounts: vi.fn(),
  listJobs: vi.fn(),
  getJob: vi.fn(),
  createJob: vi.fn(),
  retryJob: vi.fn(),
  pollJob: vi.fn(),
  retractJob: vi.fn(),
  cancelJob: vi.fn(),
}));

vi.mock("./publishing-api", () => ({ publishingApi: publishingApiMock }));

const platforms: PublishingPlatform[] = [
  {
    platform: "douyin",
    display_name: "Douyin",
    adapter_connected: false,
    supports_oauth: false,
    supports_publish: false,
    supports_schedule: false,
    supports_status_polling: false,
    supports_retract: false,
    supports_cover_update: false,
    unavailable_reason: "official_adapter_not_connected",
  },
  {
    platform: "hongguo",
    display_name: "Hongguo",
    adapter_connected: false,
    supports_oauth: false,
    supports_publish: false,
    supports_schedule: false,
    supports_status_polling: false,
    supports_retract: false,
    supports_cover_update: false,
    unavailable_reason: "official_adapter_not_connected",
  },
];

const accounts: PublishingAccount[] = [
  {
    id: "account-1",
    platform: "douyin",
    platform_account_id: "douyin-user-1",
    account_name: "Studio account",
    scopes: [],
    status: "active",
  },
];

const job: PublishJob = {
  id: "job-1",
  artifact_id: "artifact-1",
  review_snapshot_id: "review-1",
  account_id: "account-1",
  platform: "douyin",
  status: "queued",
  attempt: 1,
  max_attempts: 3,
  external_status: null,
};

function mockInitialData(
  initialPlatforms: PublishingPlatform[] = platforms,
  initialAccounts: PublishingAccount[] = accounts,
) {
  publishingApiMock.listPlatforms.mockResolvedValue(initialPlatforms);
  publishingApiMock.listAccounts.mockResolvedValue(initialAccounts);
  publishingApiMock.listJobs.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
}

describe("PublishingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/app/publishing");
    mockInitialData();
  });

  it("shows platform capabilities, official adapter warnings, and connected accounts", async () => {
    render(<PublishingPage />);

    expect(await screen.findByRole("heading", { name: "平台能力" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "抖音" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "红果" })).toBeInTheDocument();
    expect(screen.getAllByText("官方适配器未接入")).toHaveLength(2);
    expect(screen.getAllByText("Studio account")).toHaveLength(2);
    expect(screen.getByText("正常")).toBeInTheDocument();
  });

  it("disables publishing instead of pretending that an unconnected platform succeeded", async () => {
    render(<PublishingPage />);

    const publishButton = await screen.findByRole("button", { name: "创建发布任务" });
    expect(publishButton).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("final-artifact-id"), { target: { value: "artifact-1" } });
    fireEvent.change(screen.getByPlaceholderText("review-snapshot-id"), { target: { value: "review-1" } });
    fireEvent.submit(publishButton.closest("form")!);

    expect(publishingApiMock.createJob).not.toHaveBeenCalled();
  });

  it("prefills artifact and review snapshot IDs from the URL", async () => {
    window.history.replaceState({}, "", "/app/publishing?artifact_id=artifact-1&review_snapshot_id=review-1");

    render(<PublishingPage />);

    expect(await screen.findByDisplayValue("artifact-1")).toBeInTheDocument();
    expect(screen.getByDisplayValue("review-1")).toBeInTheDocument();
  });

  it("loads a job from the URL and exposes poll and retry actions", async () => {
    window.history.replaceState({}, "", "/app/publishing?job_id=job-1");
    publishingApiMock.getJob.mockResolvedValue(job);
    publishingApiMock.pollJob.mockResolvedValue({ ...job, status: "failed_retryable" });
    publishingApiMock.retryJob.mockResolvedValue({ ...job, status: "queued", attempt: 2 });

    render(<PublishingPage />);

    expect(await screen.findByText("douyin · job-1")).toBeInTheDocument();
    expect(screen.getByText("状态: queued")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "轮询状态" }));
    await waitFor(() => expect(publishingApiMock.pollJob).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText("状态: failed_retryable")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(publishingApiMock.retryJob).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText("状态: queued")).toBeInTheDocument();
  });

  it("only enables retry for retryable failed jobs", async () => {
    window.history.replaceState({}, "", "/app/publishing?job_id=job-1");
    publishingApiMock.getJob.mockResolvedValue({ ...job, status: "failed_retryable" });
    publishingApiMock.retryJob.mockResolvedValue({ ...job, status: "queued", attempt: 2 });

    render(<PublishingPage />);

    expect(await screen.findByText("状态: failed_retryable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "轮询状态" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "撤回" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(publishingApiMock.retryJob).toHaveBeenCalledWith("job-1"));
  });


  it("cancels an active job and updates the selected job and history", async () => {
    window.history.replaceState({}, "", "/app/publishing?job_id=job-1");
    publishingApiMock.getJob.mockResolvedValue({ ...job, status: "queued", project_name: "demo" });
    publishingApiMock.cancelJob.mockResolvedValue({ ...job, status: "canceled", error_code: "canceled_by_user" });

    render(<PublishingPage />);

    expect(await screen.findByText("状态: queued")).toBeInTheDocument();
    const cancelButton = screen.getByRole("button", { name: "取消任务" });
    expect(cancelButton).toBeEnabled();

    fireEvent.click(cancelButton);
    await waitFor(() => expect(publishingApiMock.cancelJob).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText("状态: canceled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消任务" })).toBeDisabled();
  });

  it("does not allow cancellation or other active actions after a job is canceled", async () => {
    window.history.replaceState({}, "", "/app/publishing?job_id=job-1");
    publishingApiMock.getJob.mockResolvedValue({ ...job, status: "canceled", project_name: "demo" });

    render(<PublishingPage />);

    expect(await screen.findByText("状态: canceled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消任务" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "轮询状态" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重试" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "撤回" })).toBeDisabled();
  });

  it("retracts a published job when the platform supports retract", async () => {
    window.history.replaceState({}, "", "/app/publishing?job_id=job-1");
    publishingApiMock.listPlatforms.mockResolvedValue([{ ...platforms[0], supports_retract: true }]);
    publishingApiMock.getJob.mockResolvedValue({ ...job, status: "published" });
    publishingApiMock.retractJob.mockResolvedValue({ ...job, status: "retracted" });

    render(<PublishingPage />);

    expect(await screen.findByText("状态: published")).toBeInTheDocument();
    const retractButton = screen.getByRole("button", { name: "撤回" });
    expect(retractButton).toBeEnabled();

    fireEvent.click(retractButton);
    await waitFor(() => expect(publishingApiMock.retractJob).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText("状态: retracted")).toBeInTheDocument();
  });

  it("shows API failures and does not create a fake job", async () => {
    publishingApiMock.listPlatforms.mockRejectedValue(new Error("network unavailable"));

    render(<PublishingPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("请求失败：network unavailable");
    expect(screen.getByText("尚未选择发布任务。")).toBeInTheDocument();
    expect(publishingApiMock.createJob).not.toHaveBeenCalled();
  });
});





