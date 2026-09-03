import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@/i18n";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useConfigStatusStore } from "@/stores/config-status-store";
import { AgentConfigTab } from "@/components/pages/AgentConfigTab";
import type { GetSystemConfigResponse } from "@/types";
import type {
  AgentCredential,
  PresetProvider,
} from "@/types/agent-credential";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConfigResponse(): GetSystemConfigResponse {
  return {
    settings: {
      default_video_backend: "",
      default_image_backend: "",
      default_text_backend: "",
      text_backend_simple: "",
      text_backend_complex: "",
      video_generate_audio: true,
      anthropic_api_key: { is_set: false, masked: null },
      anthropic_base_url: "",
      anthropic_model: "",
      anthropic_default_haiku_model: "",
      anthropic_default_opus_model: "",
      anthropic_default_sonnet_model: "",
      claude_code_subagent_model: "",
      agent_session_cleanup_delay_seconds: 300,
      agent_max_concurrent_sessions: 5,
    },
    options: {
      video_backends: [],
      image_backends: [],
      text_backends: [],
    },
  } as unknown as GetSystemConfigResponse;
}

function makePreset(overrides?: Partial<PresetProvider>): PresetProvider {
  return {
    id: "anthropic",
    sdk_type: "claude",
    display_name: "Anthropic",
    icon_key: "anthropic",
    messages_url: "https://api.anthropic.com",
    discovery_url: "https://api.anthropic.com/v1/models",
    default_model: "claude-sonnet-4",
    suggested_models: ["claude-sonnet-4", "claude-haiku-4-5"],
    docs_url: null,
    api_key_url: null,
    notes: null,
    api_key_pattern: null,
    is_recommended: true,
    supportsDiscovery: true,
    ...overrides,
  };
}

function makeCredential(overrides?: Partial<AgentCredential>): AgentCredential {
  return {
    id: 1,
    sdk_type: "claude",
    protocol: "anthropic_messages",
    preset_id: "anthropic",
    display_name: "Anthropic 主号",
    icon_key: "anthropic",
    base_url: "https://api.anthropic.com",
    api_key_masked: "sk-ant-***",
    model: "claude-sonnet-4",
    haiku_model: null,
    sonnet_model: null,
    opus_model: null,
    subagent_model: null,
    model_map: null,
    is_active: true,
    created_at: "2026-04-21T00:00:00Z",
    ...overrides,
  };
}

function setupBaseMocks(opts?: { credentials?: AgentCredential[] }) {
  vi.spyOn(API, "getSystemConfig").mockResolvedValue(makeConfigResponse());
  vi.spyOn(API, "listAgentCredentials").mockResolvedValue({
    credentials: opts?.credentials ?? [],
  });
  vi.spyOn(API, "listAgentPresetProviders").mockResolvedValue({
    providers: [makePreset()],
    custom_sentinel_id: "__custom__",
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AgentConfigTab — credentials directory", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    useConfigStatusStore.setState(useConfigStatusStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  it("renders empty hint when no credentials are present", async () => {
    setupBaseMocks();
    render(<AgentConfigTab visible />);

    expect(
      await screen.findByTestId("credential-list-empty"),
    ).toBeInTheDocument();
  });

  it('shows the "+ Add credential" button in Section 1', async () => {
    setupBaseMocks();
    render(<AgentConfigTab visible />);

    // Use translated text + leading "+"
    const btn = await screen.findByRole("button", { name: /\+ 添加供应商/ });
    expect(btn).toBeInTheDocument();
  });

  it("renders existing credentials in the list", async () => {
    setupBaseMocks({ credentials: [makeCredential()] });
    render(<AgentConfigTab visible />);

    expect(await screen.findByText("Anthropic 主号")).toBeInTheDocument();
    expect(
      screen.getByText(/sk-ant-\*\*\*/),
    ).toBeInTheDocument();
  });

  it("opens edit modal when edit button clicked", async () => {
    setupBaseMocks({ credentials: [makeCredential()] });
    render(<AgentConfigTab visible />);

    // 等待列表渲染
    await screen.findByText("Anthropic 主号");

    const user = userEvent.setup();
    const editBtn = screen.getByRole("button", {
      name: /edit|编辑|Chỉnh sửa/i,
    });
    await user.click(editBtn);

    // edit modal 出现，标题应为 edit_credential 翻译
    expect(
      await screen.findByRole("heading", {
        name: /edit[_ ]credential|编辑凭证|Chỉnh sửa xác thực/i,
      }),
    ).toBeInTheDocument();
  });

  it("saves multiple model-map entries when editing a credential", async () => {
    const existing = makeCredential({
      model_map: [
        {
          menu_name: "DeepSeek V4 Flash",
          request_model: "deepseek-v4-flash",
          context_window: null,
        },
      ],
    });
    setupBaseMocks({ credentials: [existing] });
    const updateSpy = vi.spyOn(API, "updateAgentCredential").mockResolvedValue(
      makeCredential({ model_map: [] }),
    );
    render(<AgentConfigTab visible />);

    await screen.findByText("Anthropic 主号");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /edit|编辑|Chỉnh sửa/i }));
    await screen.findByRole("heading", { name: /编辑凭证/ });

    // 编辑 modal 初始展示已有的 1 条映射
    expect(screen.getAllByLabelText(/菜单显示名/)).toHaveLength(1);

    // 添加第 2 条并填写实际请求模型
    await user.click(screen.getByRole("button", { name: /添加模型/ }));
    expect(screen.getAllByLabelText(/菜单显示名/)).toHaveLength(2);
    const requestModelInputs = screen.getAllByLabelText(/实际请求模型/);
    await user.type(requestModelInputs[1], "deepseek-v4-pro");

    // 编辑 modal 内提交（页面其它区域可能也有「保存」按钮，需限定范围）
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /保存/ }));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(
        expect.any(Number),
        expect.objectContaining({
          model_map: expect.arrayContaining([
            expect.objectContaining({ request_model: "deepseek-v4-flash" }),
            expect.objectContaining({ request_model: "deepseek-v4-pro" }),
          ]),
        }),
      );
    });
  });
});

