import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { UserMenu } from "./UserMenu";
import { useAuthStore } from "@/stores/auth-store";
import i18n from "@/i18n";

function renderMenu() {
  const { hook } = memoryLocation({ path: "/app/projects" });
  return render(
    <Router hook={hook}>
      <UserMenu />
    </Router>,
  );
}

describe("UserMenu", () => {
  beforeEach(() => {
    useAuthStore.setState(useAuthStore.getInitialState(), true);
    vi.restoreAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("用户名未知（匿名模式 / verify 未恢复）时不渲染", () => {
    useAuthStore.setState({ username: null, role: null, isAuthenticated: true });
    renderMenu();
    expect(screen.queryByRole("button", { name: /账号菜单/i })).not.toBeInTheDocument();
  });

  it("显示用户名，展开后可见角色标签与登出", async () => {
    useAuthStore.setState({ username: "admin", role: "admin", isAuthenticated: true });
    const user = userEvent.setup();
    renderMenu();

    const trigger = screen.getByRole("button", { name: /账号菜单/ });
    expect(trigger).toHaveTextContent("admin");

    await user.click(trigger);
    expect(screen.getByText(i18n.t("common:role_admin"))).toBeInTheDocument();
    expect(screen.getByText(i18n.t("common:logout"))).toBeInTheDocument();
  });

  it("普通用户显示 user 角色标签", async () => {
    useAuthStore.setState({ username: "alice", role: "user", isAuthenticated: true });
    const user = userEvent.setup();
    renderMenu();
    await user.click(screen.getByRole("button", { name: /账号菜单/ }));
    expect(screen.getByText(i18n.t("common:role_user"))).toBeInTheDocument();
  });

  it("点击登出：清除本地认证状态并回到登录页", async () => {
    useAuthStore.setState({ username: "admin", role: "admin", isAuthenticated: true });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ status: 204, ok: true, json: async () => ({}) }),
    );
    const user = userEvent.setup();
    const { hook, history } = memoryLocation({ path: "/app/projects", record: true });
    render(
      <Router hook={hook}>
        <UserMenu />
      </Router>,
    );

    await user.click(screen.getByRole("button", { name: /账号菜单/ }));
    await user.click(screen.getByText(i18n.t("common:logout")));

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/auth/logout",
      expect.objectContaining({ method: "POST" }),
    );
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().username).toBeNull();
    await act(async () => {});
    expect(history.at(-1)).toBe("/login");
  });
});
