import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth-store";
import { getToken } from "@/utils/auth";

describe("auth-store GitHub callback token", () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      username: null,
      role: null,
      isAuthenticated: false,
      isLoading: true,
    });
    window.localStorage.clear();
    window.history.replaceState(null, "", "/login");
    vi.unstubAllGlobals();
  });

  it("consumes the hash token, persists it, and backfills the profile via /auth/verify", async () => {
    window.location.hash = "#token=gh-jwt-token";

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ username: "octocat", role: "user" }),
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    useAuthStore.getState().initialize();

    await vi.waitFor(() => {
      expect(useAuthStore.getState().isAuthenticated).toBe(true);
    });

    expect(getToken()).toBe("gh-jwt-token");
    expect(useAuthStore.getState().username).toBe("octocat");
    expect(useAuthStore.getState().role).toBe("user");
    // hash 被消费并清理，避免刷新重复处理
    expect(window.location.hash).toBe("");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/auth/verify", expect.anything());
  });

  it("ignores an absent hash and falls back to the stored token path", () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: vi.fn().mockResolvedValue({}),
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    useAuthStore.getState().initialize();

    // 无 token 无 hash：走 /auth/status 探测分支
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/auth/status", expect.anything());
  });
});
