import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import type { CustomProviderInfo } from "@/types";
import { useEndpointCatalogStore } from "@/stores/endpoint-catalog-store";

import { CustomProviderForm } from "./CustomProviderForm";

const provider: CustomProviderInfo = {
  id: 7,
  display_name: "DeepSeek",
  discovery_format: "openai",
  base_url: "https://api.deepseek.com",
  api_key_masked: "sk-test…1234",
  models: [
    {
      id: 1,
      model_id: "deepseek-configured",
      display_name: "Configured model",
      endpoint: "openai-chat",
      is_default: true,
      is_enabled: true,
      price_unit: null,
      price_input: null,
      price_output: null,
      currency: null,
      supported_durations: null,
      resolution: null,
      system_capabilities: null,
      capability_overrides: null,
      global_bucket_refs: [],
    },
  ],
  created_at: "2026-05-11T00:00:00Z",
  image_max_workers: null,
  video_max_workers: null,
  audio_max_workers: null,
  is_enabled: true,
};

beforeEach(() => {
  vi.restoreAllMocks();
  useEndpointCatalogStore.setState({
    endpoints: [
      {
        key: "openai-chat",
        media_type: "text",
        family: "openai",
        display_name_key: "endpoint_openai_chat",
        request_method: "POST",
        request_path_template: "/v1/chat/completions",
        image_capabilities: null,
        end_image_capable: false,
      },
    ],
    endpointToMediaType: { "openai-chat": "text" },
    endpointPaths: { "openai-chat": { method: "POST", path: "/v1/chat/completions" } },
    endpointToImageCapabilities: {},
    endpointToEndImageCapable: { "openai-chat": false },
    loading: false,
    initialized: true,
  });
});

describe("CustomProviderForm discovery state", () => {
  it("clears stale discovered names after a later request fails but keeps configured rows", async () => {
    const discoverSpy = vi
      .spyOn(API, "discoverModelsForProvider")
      .mockResolvedValueOnce({
        models: [
          {
            model_id: "deepseek-live",
            display_name: "DeepSeek Live",
            endpoint: "openai-chat",
            is_default: false,
            is_enabled: true,
          },
        ],
      })
      .mockRejectedValueOnce(new Error("Connection error"));

    render(<CustomProviderForm existing={provider} onSaved={vi.fn()} onCancel={vi.fn()} />);

    const discoverButton = screen.getByRole("button", { name: "获取模型列表" });
    fireEvent.click(discoverButton);
    await waitFor(() => expect(discoverSpy).toHaveBeenCalledTimes(1));
    expect(screen.getByText("已发现模型")).toBeInTheDocument();
    expect(screen.getByText("deepseek-live")).toBeInTheDocument();
    expect(screen.getByDisplayValue("deepseek-configured")).toBeInTheDocument();

    fireEvent.click(discoverButton);
    await waitFor(() => expect(discoverSpy).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("已发现模型")).not.toBeInTheDocument();
    expect(screen.queryByText("deepseek-live")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("deepseek-configured")).toBeInTheDocument();
  });
});
