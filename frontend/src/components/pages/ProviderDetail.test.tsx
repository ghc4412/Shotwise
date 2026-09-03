import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import type { ProviderConfigDetail, ModelInfoResponse } from "@/types";

import { ProviderDetail } from "./ProviderDetail";

const mockModel = (overrides: Partial<ModelInfoResponse> = {}): ModelInfoResponse => ({
  display_name: "Veo 3.1",
  media_type: "video",
  capabilities: [],
  default: false,
  supported_durations: [5, 8],
  duration_resolution_constraints: {},
  resolutions: [],
  has_audio_track: true,
  audio_switch_controllable: false,
  voice_consistency: "soft",
  ...overrides,
});

const mockDetail = (overrides: Partial<ProviderConfigDetail> = {}): ProviderConfigDetail => ({
  id: "gemini-aistudio",
  display_name: "AI Studio",
  description: "Google AI Studio",
  status: "ready",
  // media_types 置空：让「视频/文本」徽章只来自模型行，避免与 Capabilities 区块重复匹配
  media_types: [],
  fields: [],
  supports_base_url: false,
  secret_fields: [],
  secret_field_groups: [],
  enabled: true,
  models: {
    "veo-3.1-generate-preview": mockModel(),
    "gemini-3-flash-preview": mockModel({
      display_name: "Gemini 3 Flash",
      media_type: "text",
      default: true,
      supported_durations: [],
    }),
  },
  ...overrides,
});

async function renderDetail(overrides?: Partial<ProviderConfigDetail>) {
  vi.spyOn(API, "getProviderConfig").mockResolvedValue(mockDetail(overrides));
  vi.spyOn(API, "listCredentials").mockResolvedValue({ credentials: [] });
  render(<ProviderDetail providerId="gemini-aistudio" />);
  // 等待详情加载完成（模型列表标题出现）
  await screen.findByText("模型列表");
}

describe("pages/ProviderDetail preset model list", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the registry model list below credentials with type filter chips", async () => {
    await renderDetail();

    // 模型行：model_id + 类型徽章 + 支持秒数（默认徽章已按需求移除）
    expect(screen.getByText("veo-3.1-generate-preview")).toBeInTheDocument();
    expect(screen.getByText("gemini-3-flash-preview")).toBeInTheDocument();
    expect(screen.getAllByText("视频").length).toBeGreaterThan(0);
    expect(screen.getByText("支持秒数：5, 8s")).toBeInTheDocument();
    expect(screen.queryByText("默认")).not.toBeInTheDocument();

    // 行内顺序：支持秒数显示在媒体类型徽章之前（videoChip 在 durationsLabel 之后）
    const modelRow = screen.getByText("veo-3.1-generate-preview").parentElement;
    const durationsLabel = within(modelRow!).getByText("支持秒数：5, 8s");
    const videoChip = within(modelRow!).getByText("视频");
    expect(
      durationsLabel.compareDocumentPosition(videoChip) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // 顶部筛选按钮：全部 + 该供应商存在的类型（video/text，无 audio/image 标签）
    expect(screen.getByRole("button", { name: "全部" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "视频" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "文本" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "音频" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "图片" })).not.toBeInTheDocument();

    // 位置：模型列表位于密钥管理（「添加供应商」）下方 —— 添加供应商按钮在模型列表标题之前
    const addCredentialBtn = await screen.findByRole("button", { name: "添加供应商" });
    const modelTitle = screen.getByText("模型列表");
    expect(
      modelTitle.compareDocumentPosition(addCredentialBtn) & Node.DOCUMENT_POSITION_PRECEDING,
    ).toBeTruthy();
  });

  it("filters model rows by media type chip", async () => {
    await renderDetail();
    expect(screen.getByText("veo-3.1-generate-preview")).toBeInTheDocument();
    expect(screen.getByText("gemini-3-flash-preview")).toBeInTheDocument();

    // 点「视频」→ 只显示视频模型
    fireEvent.click(screen.getByRole("button", { name: "视频" }));
    expect(screen.getByText("veo-3.1-generate-preview")).toBeInTheDocument();
    expect(screen.queryByText("gemini-3-flash-preview")).not.toBeInTheDocument();

    // 点「全部」→ 恢复显示
    fireEvent.click(screen.getByRole("button", { name: "全部" }));
    expect(screen.getByText("veo-3.1-generate-preview")).toBeInTheDocument();
    expect(screen.getByText("gemini-3-flash-preview")).toBeInTheDocument();
  });

  it("updates the model list with models discovered by connection testing", async () => {
    const testResult = {
      success: true,
      available_models: ["veo-3.1-generate-preview", "vendor-new-model"],
      model_types: {
        "veo-3.1-generate-preview": "video",
        "vendor-new-model": "image",
      },
      message: "连接成功",
    };
    vi.spyOn(API, "getProviderConfig").mockResolvedValue(mockDetail());
    vi.spyOn(API, "listCredentials").mockResolvedValue({ credentials: [
      {
        id: 1,
        provider: "gemini-aistudio",
        name: "默认账号",
        api_key_masked: "sk-x…abcd",
        credentials_filename: null,
        base_url: null,
        is_active: true,
        created_at: "2026-06-01T00:00:00Z",
      },
    ] });
    vi.spyOn(API, "testProviderConnection").mockResolvedValue(testResult);

    render(<ProviderDetail providerId="gemini-aistudio" />);
    await screen.findByText("模型列表");
    fireEvent.click(await screen.findByRole("button", { name: /测试 默认账号 连接/ }));

    await waitFor(() => expect(screen.getByText("vendor-new-model")).toBeInTheDocument());
    const newModelRow = screen.getByText("vendor-new-model").parentElement;
    expect(within(newModelRow!).getByText("图片")).toBeInTheDocument();
    expect(screen.queryByText("已发现模型")).not.toBeInTheDocument();
    expect(screen.getAllByText("veo-3.1-generate-preview")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "图片" }));
    expect(screen.getByText("vendor-new-model")).toBeInTheDocument();
    expect(screen.queryByText("veo-3.1-generate-preview")).not.toBeInTheDocument();
  });

  it("restores persisted discovered models after loading the provider config", async () => {
    await renderDetail({
      models: undefined,
      discovered_models: ["vendor-video"],
      model_type_overrides: { "vendor-video": "video" },
    });

    expect(screen.getByText("vendor-video")).toBeInTheDocument();
    const modelRow = screen.getByText("vendor-video").parentElement;
    expect(within(modelRow!).getByText("视频")).toBeInTheDocument();
  });

  it("persists a manually selected type for a discovered model", async () => {
    vi.spyOn(API, "patchProviderModelTypes").mockResolvedValue({
      model_type_overrides: { "vendor-unknown": "video" },
      discovered_models: ["vendor-unknown"],
    });

    await renderDetail({
      models: undefined,
      discovered_models: ["vendor-unknown"],
      model_type_overrides: {},
    });

    const modelRow = screen.getByText("vendor-unknown").parentElement;
    const typeSelect = within(modelRow!).getByRole("combobox", { name: /设置模型类型: vendor-unknown/ });
    expect(typeSelect).toHaveValue("unknown");

    fireEvent.change(typeSelect, { target: { value: "video" } });

    await waitFor(() => {
      expect(API.patchProviderModelTypes).toHaveBeenCalledWith("gemini-aistudio", {
        "vendor-unknown": "video",
      });
    });
    expect(typeSelect).toHaveValue("video");
    expect(within(modelRow!).getByText("视频")).toBeInTheDocument();
  });

  it("renders no model section when detail has no models", async () => {
    vi.spyOn(API, "getProviderConfig").mockResolvedValue(mockDetail({ models: undefined }));
    vi.spyOn(API, "listCredentials").mockResolvedValue({ credentials: [] });

    render(<ProviderDetail providerId="gemini-aistudio" />);

    await waitFor(() => {
      expect(screen.getByText("AI Studio")).toBeInTheDocument();
    });
    expect(screen.queryByText("模型列表")).not.toBeInTheDocument();
  });
});
