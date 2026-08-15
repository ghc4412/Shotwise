import { useEffect, useRef, useState } from "react";
import { useLocation } from "wouter";
import { ChevronDown, LogOut, Settings } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuthStore } from "@/stores/auth-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useDemoWorkbench } from "@/onboarding/use-demo-workbench";
import { rememberSettingsReturnTo } from "@/utils/settings-return-to";
import { voidPromise } from "@/utils/async";
import { DROPDOWN_PANEL_STYLE, GHOST_BTN_CLS } from "@/components/ui/darkroom-tokens";

interface UserMenuProps {
  /** 紧凑模式：只显示头像按钮（工作台顶栏用）；默认头像 + 用户名。 */
  compact?: boolean;
}

/**
 * 用户菜单：显示当前登录用户名与角色，提供设置跳转与登出入口。
 *
 * 用户名/角色来自 auth-store（登录时写入、刷新后经 /auth/verify 恢复）；
 * 匿名模式（AUTH_ENABLED=false，username 为 null）下不渲染。
 * 设置：总是跳转全局设置页（CONTROL BOOTH，admin-only）——与顶栏齿轮
 * （项目内 → 项目设置）区分；普通用户无项目/非演示时不渲染该入口。
 * 登出：调用后端 /auth/logout（仅审计日志，失败不阻塞），随后清除本地
 * token 并回到登录页——JWT 无状态，本地清除即失效。
 */
export function UserMenu({ compact = false }: UserMenuProps) {
  const { t } = useTranslation("common");
  const [, setLocation] = useLocation();
  const username = useAuthStore((s) => s.username);
  const role = useAuthStore((s) => s.role);
  const currentProjectName = useProjectsStore((s) => s.currentProjectName);
  const demoMode = useDemoWorkbench();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // 外部点击 / Escape 关闭下拉
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!username) return null;

  const initial = username.trim().charAt(0).toUpperCase() || "?";
  const isAdmin = role === "admin";
  // 可见性与顶栏齿轮一致：普通用户无项目/非演示时看不到设置入口（全局设置 admin-only）
  const showSettings = !(role === "user" && !currentProjectName && !demoMode);

  const handleLogout = async () => {
    setOpen(false);
    try {
      const token = useAuthStore.getState().token;
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch {
      // 登出端点仅记录审计日志；token 由本地清除即失效，失败不阻塞
    }
    useAuthStore.getState().logout();
    setLocation("/login");
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("account_menu", { username })}
        title={username}
        className={`${GHOST_BTN_CLS} ${compact ? "!px-2 !py-1" : ""}`}
      >
        <span
          aria-hidden
          className="grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-bold"
          style={{
            background:
              "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
            color: "oklch(0.14 0 0)",
          }}
        >
          {initial}
        </span>
        {!compact && <span className="max-w-[140px] truncate text-[12px]">{username}</span>}
        <ChevronDown aria-hidden className={`h-3 w-3 text-text-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          role="menu"
          aria-label={username}
          className="absolute right-0 top-full z-50 mt-2 w-[220px] overflow-hidden rounded-[10px] border border-hairline-soft shadow-[0_18px_48px_-16px_oklch(0_0_0/0.6)]"
          style={DROPDOWN_PANEL_STYLE}
        >
          <div className="border-b border-hairline-soft px-4 py-3">
            <div className="truncate text-[13px] font-semibold text-text">{username}</div>
            <div className="mt-1 inline-flex items-center gap-1.5 rounded-full border border-hairline-soft bg-bg-grad-a/50 px-2 py-px text-[10px] font-medium uppercase tracking-[0.1em] text-text-3">
              <span
                aria-hidden
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: isAdmin ? "var(--color-accent-2)" : "var(--color-text-3)" }}
              />
              {isAdmin ? t("role_admin") : t("role_user")}
            </div>
          </div>
          {showSettings && (
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              // 普通用户进全局设置会被 AdminGuard 重定向回项目列表，有项目时直接进
              // 项目设置（与顶栏齿轮口径一致）；admin / 演示模式走全局设置（CONTROL
              // BOOTH），并记录来源路径，返回按钮回到原地
              if (role === "user" && currentProjectName) {
                setLocation(`~/app/projects/${encodeURIComponent(currentProjectName)}/settings`);
              } else {
                rememberSettingsReturnTo(window.location.pathname);
                setLocation("~/app/settings");
              }
            }}
            className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-[12.5px] text-text-2 transition-colors hover:bg-bg-grad-a hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <Settings aria-hidden className="h-3.5 w-3.5 text-text-3" />
            {t("settings")}
          </button>
          )}
          <button
            type="button"
            role="menuitem"
            onClick={voidPromise(handleLogout)}
            className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-[12.5px] text-text-2 transition-colors hover:bg-bg-grad-a hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <LogOut aria-hidden className="h-3.5 w-3.5 text-text-3" />
            {t("logout")}
          </button>
        </div>
      )}
    </div>
  );
}
