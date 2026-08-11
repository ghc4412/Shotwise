import { create } from "zustand";
import { getToken, setToken as saveToken, clearToken } from "@/utils/auth";

interface AuthState {
  token: string | null;
  username: string | null;
  role: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  initialize: () => void;
  login: (token: string, username: string, role: string) => void;
  logout: () => void;
  setLoading: (loading: boolean) => void;
}

/** 从 URL hash 中取出 GitHub OAuth 回调带来的 token 并清掉 hash。
 *
 * 后端回调以 ``/app/projects#token=<jwt>`` 重定向回前端；token 放 fragment
 * 而非 query，避免进入服务端访问日志。取走后立即清理，防止刷新时重复消费。
 */
function consumeHashToken(): string | null {
  if (typeof window === "undefined") return null;
  const match = window.location.hash.match(/^#token=([^&]+)/);
  if (!match) return null;
  const token = decodeURIComponent(match[1]);
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  return token;
}

/** 校验 token 并回填 username/role（GitHub 回调登录后 token 刚拿到，凭据未落盘）。 */
function runVerify(token: string, set: (partial: Partial<AuthState>) => void): void {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);
  fetch("/api/v1/auth/verify", {
    headers: { Authorization: `Bearer ${token}` },
    signal: controller.signal,
  })
    .then(async (res) => {
      if (res.status === 401) {
        // token 过期/无效：清掉并回到登录页
        clearToken();
        set({ token: null, username: null, role: null, isAuthenticated: false });
        return;
      }
      if (!res.ok) throw new Error(`status ${res.status}`);
      const payload: unknown = await res.json();
      const data = payload as { username?: unknown; role?: unknown };
      if (typeof data.username !== "string") {
        throw new Error("invalid /auth/verify payload");
      }
      set({
        username: data.username,
        role: typeof data.role === "string" ? data.role : "admin",
        isAuthenticated: true,
      });
    })
    .catch(() => {
      // 非 401 错误（网络抖动等）：token 仍存在，先放行主界面；
      // 用户名/角色未知时用户菜单不渲染，下次刷新会重试。
      set({ isAuthenticated: true });
    })
    .finally(() => {
      clearTimeout(timeoutId);
      set({ isLoading: false });
    });
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  username: null,
  role: null,
  isAuthenticated: false,
  isLoading: true,

  initialize: () => {
    const hashToken = consumeHashToken();
    const token = hashToken ?? getToken();
    if (token) {
      // 有 token 时调 /auth/verify：校验 token 有效性，同时恢复用户名与角色
      // （token 只存在 localStorage，username/role 不落盘，刷新后必须重新拉取）。
      if (hashToken) saveToken(token);
      runVerify(token, set);
      return;
    }
    // 无 token 时先问后端是否启用了鉴权。`AUTH_ENABLED=false` 时后端全链路
    // bypass，前端也应该跳过登录页直接进主界面。超时 / 网络异常 / 响应 shape
    // 异常时 fail-closed 退回到登录页，避免误把损坏响应当成"无需鉴权"放行。
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    fetch("/api/v1/auth/status", { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`status ${res.status}`);
        const payload: unknown = await res.json();
        if (
          typeof payload !== "object" ||
          payload === null ||
          typeof (payload as { enabled?: unknown }).enabled !== "boolean"
        ) {
          throw new Error("invalid /auth/status payload");
        }
        const { enabled } = payload as { enabled: boolean };
        if (!enabled) {
          set({ isAuthenticated: true });
        }
      })
      .catch((err) => {
        console.warn("[auth] /auth/status fetch failed; defaulting to login", err);
      })
      .finally(() => {
        clearTimeout(timeoutId);
        set({ isLoading: false });
      });
  },

  login: (token, username, role) => {
    saveToken(token);
    set({ token, username, role, isAuthenticated: true, isLoading: false });
  },

  logout: () => {
    clearToken();
    set({ token: null, username: null, role: null, isAuthenticated: false });
  },

  setLoading: (isLoading) => set({ isLoading }),
}));
