import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import type { PresetProvider } from "@/types/agent-credential";

import { AddCredentialModal } from "../AddCredentialModal";

beforeEach(() => {
  // 默认 mock：没有自定义供应商，import 按钮不显示，不污染既有断言
  vi.spyOn(API, "listCustomProviders").mockResolvedValue({ providers: [] });
});

const presets: PresetProvider[] = [
  {
    id: "deepseek",
    sdk_type: "claude",
    display_name: "DeepSeek",
    icon_key: "DeepSeek",
    messages_url: "https://api.deepseek.com/anthropic",
    discovery_url: "https://api.deepseek.com",
    default_model: "deepseek-chat",
    suggested_models: ["deepseek-chat"],
    docs_url: null,
    api_key_url: "https://platform.deepseek.com/api_keys",
    notes: null,
    api_key_pattern: null,
    is_recommended: true,
    supportsDiscovery: true,
  },
];

const presetsWithSecond: PresetProvider[] = [
  ...presets,
  {
    id: "moonshot",
    sdk_type: "claude",
    display_name: "Moonshot",
    icon_key: "Moonshot",
    messages_url: "https://api.moonshot.cn/anthropic",
    discovery_url: "https://api.moonshot.cn",
    default_model: "moonshot-v1",
    suggested_models: ["moonshot-v1"],
    docs_url: null,
    api_key_url: "https://platform.moonshot.cn/api_keys",
    notes: null,
    api_key_pattern: null,
    is_recommended: false,
    supportsDiscovery: true,
  },
];

describe("AddCredentialModal", () => {
  it("renders custom config chip first", () => {
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    const chips = screen.getAllByTestId("preset-chip");
    expect(chips[0]).toHaveTextContent(/custom|自定义|Tuỳ chỉnh/i);
  });

  it("when preset chosen, base_url is shown and prefilled with messages_url", () => {
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek/i }));
    const baseUrlInput = screen.getByLabelText(
      /base[_ ]url|代理地址/i,
    ) as HTMLInputElement;
    expect(baseUrlInput).toBeInTheDocument();
    expect(baseUrlInput.value).toBe("https://api.deepseek.com/anthropic");
  });

  it("model dropdown falls back to suggested_models when no discovery results", () => {
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek/i }));
    // 未点「发现模型」：modelOptions 为空 → 下拉展示 preset.suggested_models
    const modelInput = screen.getByLabelText(/default[_ ]model|默认模型/i) as HTMLInputElement;
    const toggle = within(modelInput.parentElement as HTMLElement).getByRole("button", {
      name: /toggle[_ ]options|切换选项/i,
    });
    fireEvent.click(toggle);
    expect(screen.getByRole("option", { name: "deepseek-chat" })).toBeInTheDocument();
  });

  it("clears stale discovered models when a later discovery request fails", async () => {
    const discoverSpy = vi
      .spyOn(API, "discoverAnthropicModels")
      .mockResolvedValueOnce({
        models: [
          {
            model_id: "deepseek-v4-pro",
            display_name: "DeepSeek V4 Pro",
            endpoint: "anthropic-messages",
            is_default: true,
            is_enabled: true,
            context_window: 128000,
          },
        ],
      })
      .mockRejectedValueOnce(new Error("Connection error"));

    render(
      <AddCredentialModal
        open
        sdkType="claude"
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek/i }));
    fireEvent.change(screen.getByLabelText(/anthropic[_ ]?api[_ ]?key|Anthropic API 密钥/i), {
      target: { value: "sk-test" },
    });

    const fetchButton = screen.getByRole("button", { name: /获取模型列表/ });
    fireEvent.click(fetchButton);
    await waitFor(() => expect(discoverSpy).toHaveBeenCalledTimes(1));
    const modelInput = screen.getByLabelText(/default[_ ]model|默认模型/i);
    fireEvent.click(within(modelInput.parentElement as HTMLElement).getByRole("button", {
      name: /toggle[_ ]options|切换选项/i,
    }));
    expect(screen.getByRole("option", { name: "deepseek-v4-pro" })).toBeInTheDocument();

    fireEvent.click(fetchButton);
    await waitFor(() => expect(discoverSpy).toHaveBeenCalledTimes(2));
    await waitFor(() => {
      expect(screen.queryByRole("option", { name: "deepseek-v4-pro" })).not.toBeInTheDocument();
    });
    expect(screen.getAllByText("Connection error")).toHaveLength(2);
  });

  it("fetch button stays visible but shows toast for OpenAI Ark Agent Plan without auto-discovery", async () => {
    const arkPresets: PresetProvider[] = [
      {
        ...presets[0],
        id: "ark-agent-plan-openai",
        sdk_type: "openai",
        display_name: "火山方舟 Agent Plan",
        messages_url: "https://ark.cn-beijing.volces.com/api/plan/v3",
        discovery_url: null,
        suggested_models: ["doubao-seed-2.0-code"],
        supportsDiscovery: false,
      },
    ];
    const pushToastSpy = vi.spyOn(useAppStore.getState(), "pushToast");
    const discoverSpy = vi.spyOn(API, "discoverOpenAIModels").mockResolvedValue({
      models: [],
    });
    render(
      <AddCredentialModal
        open
        sdkType='openai'
        presets={arkPresets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /火山方舟 Agent Plan/i }));
    fireEvent.change(screen.getByLabelText(/openai[_ ]?api[_ ]?key|OpenAI API 密钥|API 密钥/i), {
      target: { value: "sk-test" },
    });
    // 按钮保留可点
    fireEvent.click(screen.getByRole("button", { name: /获取模型列表/ }));
    // 不发请求，改为弹提示
    expect(discoverSpy).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(pushToastSpy).toHaveBeenCalledWith(
        expect.stringContaining("不支持模型自动发现"),
        "warning",
      );
    });
  });

  it("keeps fetch-model button when preset data lacks supportsDiscovery (legacy response)", () => {
    // 旧版本后端 / 已加载的旧 presets 数据没有 supports_discovery 字段：
    // 缺省应视为支持发现，避免误隐藏 DeepSeek 等预设的「获取模型列表」按钮。
    const legacyPresets: PresetProvider[] = [{ ...presets[0] }];
    delete (legacyPresets[0] as { supportsDiscovery?: unknown }).supportsDiscovery;
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={legacyPresets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek/i }));
    expect(screen.getByRole("button", { name: /获取模型列表/ })).toBeInTheDocument();
  });

  it("when custom chosen, base_url input shown and empty", () => {
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getAllByTestId("preset-chip")[0]); // custom
    const input = screen.getByLabelText(
      /base[_ ]url|代理地址/i,
    ) as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe("");
  });

  it("preset submit payload uses preset_id only", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={onSubmit}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek/i }));
    fireEvent.change(screen.getByLabelText(/anthropic[_ ]?api[_ ]?key|Anthropic API 密钥/i), {
      target: { value: "sk-test" },
    });
    // 精确匹配提交按钮「添加」，避免命中模型映射的「添加模型」
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        preset_id: "deepseek",
        api_key: "sk-test",
        base_url: "https://api.deepseek.com/anthropic",
      }),
    );
  });

  it("get-api-key link rendered when preset has api_key_url", () => {
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek/i }));
    const link = screen.getByRole("link", {
      name: /get[_ ]api[_ ]key|获取/i,
    });
    expect(link).toHaveAttribute("href", "https://platform.deepseek.com/api_keys");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("calls onClose when Escape pressed", () => {
    const onClose = vi.fn();
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={onClose}
      />,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when overlay clicked", () => {
    const onClose = vi.fn();
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("modal-overlay"));
    expect(onClose).toHaveBeenCalled();
  });

  it("shows submit error when onSubmit rejects", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("boom"));
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={onSubmit}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek/i }));
    fireEvent.change(
      screen.getByLabelText(/anthropic[_ ]?api[_ ]?key|Anthropic API 密钥/i),
      { target: { value: "sk-test" } },
    );
    // 精确匹配提交按钮「添加」，避免命中模型映射的「添加模型」
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => {
      expect(screen.getByText(/boom/)).toBeInTheDocument();
    });
  });

  it("overwrites displayName when switching preset (even if user edited)", () => {
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presetsWithSecond}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek/i }));
    const nameInput = screen.getByLabelText(
      /display[_ ]name|显示名/i,
    ) as HTMLInputElement;
    expect(nameInput.value).toBe("DeepSeek");
    // 用户改名
    fireEvent.change(nameInput, { target: { value: "My Custom Name" } });
    expect(nameInput.value).toBe("My Custom Name");
    // 切换到另一个 preset → displayName 跟随预设切换
    fireEvent.click(screen.getByRole("button", { name: /Moonshot/i }));
    expect(nameInput.value).toBe("Moonshot");
  });

  it("renders edit title when mode=edit", () => {
    render(
      <AddCredentialModal
        open
        mode="edit"
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        initial={{
          preset_id: "deepseek",
          display_name: "DS Prod",
          base_url: "https://api.deepseek.com/anthropic",
          model: "deepseek-chat",
        }}
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("heading", { name: /edit[_ ]credential|编辑凭证|Chỉnh sửa xác thực/i }),
    ).toBeInTheDocument();
  });

  it("does not require apiKey in edit mode and submits with empty key", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <AddCredentialModal
        open
        mode="edit"
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        initial={{
          preset_id: "deepseek",
          display_name: "DS Prod",
          base_url: "https://api.deepseek.com/anthropic",
          model: "deepseek-chat",
        }}
        onSubmit={onSubmit}
        onClose={vi.fn()}
      />,
    );
    // 改一个非 api_key 字段触发 dirty,api_key 留空提交
    fireEvent.change(
      screen.getByLabelText(/display[_ ]name|显示名/i),
      { target: { value: "DS Prod 2" } },
    );
    const submitBtn = screen.getByRole("button", {
      name: /^save$|^保存$|^Lưu$/i,
    });
    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalled();
    });
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ api_key: "" }),
    );
  });

  it("disables submit in edit mode when no field changed", () => {
    render(
      <AddCredentialModal
        open
        mode="edit"
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        initial={{
          preset_id: "deepseek",
          display_name: "DS Prod",
          base_url: "https://api.deepseek.com/anthropic",
          model: "deepseek-chat",
        }}
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    const submitBtn = screen.getByRole("button", {
      name: /^save$|^保存$|^Lưu$/i,
    });
    expect(submitBtn).toBeDisabled();
  });

  describe("import from provider", () => {
    const sampleProvider: import("@/types/custom-provider").CustomProviderInfo = {
      id: 42,
      display_name: "DeepSeek (Custom)",
      discovery_format: "openai",
      base_url: "https://api.deepseek.com",
      api_key_masked: "sk-abcd…1234",
      models: [],
      created_at: "2026-05-11T00:00:00Z",
      image_max_workers: null,
      video_max_workers: null,
      audio_max_workers: null,
      is_enabled: true,
    };

    it("hides import button when no custom providers configured", async () => {
      render(
        <AddCredentialModal
          open
          sdkType='claude'
          presets={presets}
          customSentinelId="__custom__"
          onSubmit={vi.fn()}
          onClose={vi.fn()}
        />,
      );
      // effect 跑完后仍无按钮（默认 mock 返回空数组）
      await waitFor(() => {
        expect(API.listCustomProviders).toHaveBeenCalled();
      });
      expect(screen.queryByTestId("import-from-provider")).not.toBeInTheDocument();
    });

    it("shows import button and lists providers when available", async () => {
      vi.spyOn(API, "listCustomProviders").mockResolvedValue({
        providers: [sampleProvider],
      });

      render(
        <AddCredentialModal
          open
          sdkType='claude'
          presets={presets}
          customSentinelId="__custom__"
          onSubmit={vi.fn()}
          onClose={vi.fn()}
        />,
      );

      const btn = await screen.findByTestId("import-from-provider");
      fireEvent.click(btn);
      expect(await screen.findByTestId("import-provider-option")).toHaveTextContent(
        "DeepSeek (Custom)",
      );
    });

    it("populates base_url + api_key from selected provider", async () => {
      vi.spyOn(API, "listCustomProviders").mockResolvedValue({
        providers: [sampleProvider],
      });
      vi.spyOn(API, "getCustomProviderCredentials").mockResolvedValue({
        api_key: "sk-real-key",
        base_url: "https://api.deepseek.com/anthropic",
      });

      render(
        <AddCredentialModal
          open
          sdkType='claude'
          presets={presets}
          customSentinelId="__custom__"
          onSubmit={vi.fn()}
          onClose={vi.fn()}
        />,
      );

      fireEvent.click(await screen.findByTestId("import-from-provider"));
      fireEvent.click(await screen.findByTestId("import-provider-option"));

      const baseUrlInput = (await screen.findByLabelText(
        /base[_ ]url|代理地址/i,
      )) as HTMLInputElement;
      await waitFor(() => {
        expect(baseUrlInput.value).toBe("https://api.deepseek.com/anthropic");
      });

      const apiKeyInput = screen.getByLabelText(
        /anthropic[_ ]?api[_ ]?key|Anthropic API 密钥/i,
      ) as HTMLInputElement;
      expect(apiKeyInput.value).toBe("sk-real-key");
    });

    it("does not show import button in edit mode", async () => {
      vi.spyOn(API, "listCustomProviders").mockResolvedValue({
        providers: [sampleProvider],
      });

      render(
        <AddCredentialModal
          open
          mode="edit"
          sdkType='claude'
          presets={presets}
          customSentinelId="__custom__"
          initial={{ preset_id: "deepseek", display_name: "DS" }}
          onSubmit={vi.fn()}
          onClose={vi.fn()}
        />,
      );

      // edit 模式即使有可导入供应商也不显示按钮（避免误操作覆盖现有凭证）
      // 等几个事件循环确保 effect 不会触发（edit 模式 effect 不该调 API）
      await new Promise((r) => setTimeout(r, 0));
      expect(API.listCustomProviders).not.toHaveBeenCalled();
      expect(screen.queryByTestId("import-from-provider")).not.toBeInTheDocument();
    });
  });

  describe("test connection (draft)", () => {
    const okResult = {
      overall: "ok" as const,
      messages_probe: { success: true, status_code: 200, latency_ms: 123, error: null },
      discovery_probe: null,
      diagnosis: null,
      suggestion: null,
      derived_messages_root: "https://api.deepseek.com/anthropic",
      derived_discovery_root: "",
    };

    it("disabled until both base_url and api_key filled", () => {
      render(
        <AddCredentialModal
          open
          sdkType='claude'
          presets={presets}
          customSentinelId="__custom__"
          onSubmit={vi.fn()}
          onClose={vi.fn()}
        />,
      );
      // 初始 custom 模式：baseUrl 空 → 测试按钮禁用
      const btn = screen.getByTestId("test-connection");
      expect(btn).toBeDisabled();
    });

    it("calls testAgentConnectionDraft and renders TestResultPanel", async () => {
      const spy = vi.spyOn(API, "testAgentConnectionDraft").mockResolvedValue(okResult);
      render(
        <AddCredentialModal
          open
          sdkType='claude'
          presets={presets}
          customSentinelId="__custom__"
          onSubmit={vi.fn()}
          onClose={vi.fn()}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: /DeepSeek/i }));
      fireEvent.change(
        screen.getByLabelText(/anthropic[_ ]?api[_ ]?key|Anthropic API 密钥/i),
        { target: { value: "sk-test" } },
      );
      fireEvent.click(screen.getByTestId("test-connection"));
      await waitFor(() => {
        expect(spy).toHaveBeenCalledWith(
          expect.objectContaining({
            preset_id: "deepseek",
            base_url: "https://api.deepseek.com/anthropic",
            api_key: "sk-test",
          }),
        );
      });
      // TestResultPanel headline 渲染（test_ok 文案三语 OR-match）
      await screen.findByText(/test[_ ]ok|连通正常|Kết nối/i);
    });
  });

  it("disables preset chips in edit mode", () => {
    render(
      <AddCredentialModal
        open
        mode="edit"
        sdkType='claude'
        presets={presetsWithSecond}
        customSentinelId="__custom__"
        initial={{
          preset_id: "deepseek",
          display_name: "DS",
        }}
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    const chips = screen.getAllByTestId("preset-chip");
    for (const chip of chips) {
      expect(chip).toBeDisabled();
    }
  });

  it("renders model map editor above default model field", () => {
    render(
      <AddCredentialModal
        open
        sdkType='claude'
        presets={presets}
        customSentinelId="__custom__"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("模型映射")).toBeInTheDocument();
    // 「获取模型列表」仅保留在模型映射模块（默认模型字段上的已移除）
    expect(screen.getAllByRole("button", { name: /获取模型列表/ })).toHaveLength(1);
    expect(screen.getByRole("button", { name: /添加模型/ })).toBeInTheDocument();
    // 模型映射模块位于默认模型字段之前
    const defaultModelLabel = screen.getByText("默认模型");
    const mapTitle = screen.getByText("模型映射");
    expect(mapTitle.compareDocumentPosition(defaultModelLabel)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
});
