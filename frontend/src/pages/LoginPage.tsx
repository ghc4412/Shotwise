import { useEffect, useState, type FormEvent } from "react";
import { Eye, EyeOff, Film, Loader2, Sparkles } from "lucide-react";
import { useAutoFocus } from "@/hooks/useAutoFocus";
import { errMsg, voidPromise } from "@/utils/async";
import { useLocation, useSearch } from "wouter";
import { useTranslation } from "react-i18next";
import { useAuthStore } from "@/stores/auth-store";
import { safeReturnPath } from "@/utils/safe-url";
import { BRAND } from "@/branding";
import type { LoginResponse, ErrorResponse } from "@/api";
import { FieldLabel } from "@/components/ui/FieldLabel";
import { Reveal } from "@/components/ui/Reveal";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { ThemeAccentPicker } from "@/components/ui/ThemeAccentPicker";
import {
  ACCENT_BTN_CLS,
  ACCENT_BUTTON_STYLE,
  INPUT_CLS,
} from "@/components/ui/darkroom-tokens";

/** GitHub OAuth 回调失败时 hash 中携带的错误码 → 文案 key */
const OAUTH_ERROR_KEYS: Record<string, string> = {
  invalid_state: "oauth_error_invalid_state",
  auth_failed: "oauth_error_auth_failed",
  username_taken: "oauth_error_username_taken",
};

export function LoginPage() {
  const { t, i18n } = useTranslation(["common", "auth"]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  // GitHub 回调失败（#oauth_error=<code>）：mount 时一次性读取并清掉 hash
  const [error, setError] = useState<string>(() => {
    const match = window.location.hash.match(/^#oauth_error=([^&]+)/);
    if (!match) return "";
    const key = OAUTH_ERROR_KEYS[decodeURIComponent(match[1])];
    return key ? t(`auth:${key}`) : "";
  });
  const [loading, setLoading] = useState(false);
  const [githubConfigured, setGithubConfigured] = useState(false);
  const [, setLocation] = useLocation();
  const search = useSearch();
  const login = useAuthStore((s) => s.login);
  const usernameRef = useAutoFocus<HTMLInputElement>();

  // 探测 GitHub OAuth 是否已配置，决定是否渲染 GitHub 登录入口
  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/auth/github/config")
      .then(async (res) => {
        if (!res.ok) return;
        const payload = (await res.json()) as { configured?: unknown };
        if (!cancelled) setGithubConfigured(payload.configured === true);
      })
      .catch(() => {
        // 网络异常时按未配置处理，隐藏 GitHub 入口
        if (!cancelled) setGithubConfigured(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 消费 GitHub 回调错误 hash（error 已由 useState 惰性初始化读取，这里只清理 URL）
  useEffect(() => {
    if (/^#oauth_error=/.test(window.location.hash)) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const body = new URLSearchParams({ username, password, grant_type: "password" });
      const resp = await fetch("/api/v1/auth/token", {
        method: "POST",
        headers: { "Accept-Language": i18n.language || "zh" },
        body,
      });

      if (!resp.ok) {
        const data = (await resp.json().catch(() => ({}))) as Partial<ErrorResponse>;
        const detail = data.detail;
        throw new Error(typeof detail === "string" ? detail : t("auth:login_failed"));
      }

      const data = (await resp.json()) as LoginResponse;
      login(data.access_token, username, data.role ?? "admin");
      const returnTo = safeReturnPath(new URLSearchParams(search).get("from"));
      setLocation(returnTo ?? "/app/projects");
    } catch (err) {
      setError(errMsg(err, t("auth:login_failed")));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div data-testid="login-page" className="auth-scene relative min-h-screen overflow-hidden text-text">
      <div aria-hidden className="auth-sweep" />
      <div aria-hidden className="auth-grid" />
      <div aria-hidden className="auth-film-track auth-film-track-left" />
      <div aria-hidden className="auth-film-track auth-film-track-right" />

      <header className="auth-topbar relative z-10 flex items-center justify-between px-6 py-5 lg:px-10">
        <div className="flex items-center gap-3">
          <img src="/shotwise-mark.svg" alt="" aria-hidden className="h-10 w-10 rounded-xl shadow-lg" />
          <div>
            <div className="font-sans text-[15px] font-semibold tracking-[0.08em] text-text">{BRAND.name}</div>
            <div className="font-mono text-[9px] uppercase tracking-[0.18em] text-text-4">{t("auth:login_brand_label")}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle compact />
          <ThemeAccentPicker />
        </div>
      </header>

      <main className="auth-layout relative z-10 mx-auto grid w-full max-w-[1240px] gap-10 px-6 pb-10 pt-6 lg:grid-cols-[1.08fr_0.82fr] lg:items-center lg:px-10 lg:pb-20 lg:pt-12">
        <section className="auth-showcase min-w-0">
          <Reveal from="left" threshold={0}>
            <div className="mb-5 flex items-center gap-3 font-mono text-[10px] font-semibold uppercase tracking-[0.17em] text-accent-2">
              <span className="auth-kicker-line" />
              {t("auth:login_kicker")}
            </div>
          </Reveal>
          <Reveal from="left" delay={90} threshold={0}>
            <h1 className="auth-title max-w-[720px] whitespace-pre-line text-balance font-editorial text-[clamp(3.2rem,6.8vw,6rem)] font-normal leading-[1.05] tracking-[-0.035em] text-text">
              {t("auth:login_hero_title")}
            </h1>
          </Reveal>
          <Reveal from="left" delay={180} threshold={0}>
            <p className="mt-7 max-w-[560px] text-[15px] leading-7 text-text-2 lg:text-[17px]">{t("auth:login_hero_body")}</p>
          </Reveal>

          <Reveal from="left" delay={270} threshold={0}>
            <div className="auth-reel mt-10" aria-label={t("auth:login_reel_label")}>
              <div className="auth-reel-head">
                <span className="flex items-center gap-2"><Film className="h-3.5 w-3.5" />{t("auth:login_reel_label")}</span>
                <span className="font-mono text-[9px] tracking-[0.16em] text-text-4">{t("auth:login_reel_meta")}</span>
              </div>
              <div className="auth-reel-stage">
                <div className="auth-reel-frame auth-reel-frame-one" />
                <div className="auth-reel-frame auth-reel-frame-two" />
                <div className="auth-reel-frame auth-reel-frame-three" />
                <div className="auth-reel-copy"><Sparkles className="h-4 w-4 text-accent-2" /><span>{t("auth:login_reel_counter")}</span></div>
                <div className="auth-reel-play"><span /></div>
              </div>
              <div className="auth-reel-progress"><span /></div>
            </div>
          </Reveal>

          <Reveal from="left" delay={360} threshold={0}>
            <div className="auth-metrics mt-8 grid max-w-[620px] grid-cols-3">
              {["login_metric_worlds", "login_metric_shots", "login_metric_render"].map((key, index) => (
                <div key={key} className="auth-metric">
                  <div className="font-mono text-[9px] uppercase tracking-[0.14em] text-text-4">{t(`auth:${key}`)}</div>
                  <div className="mt-2 font-editorial text-[27px] text-text">{["01", "08", "∞"][index]}</div>
                </div>
              ))}
            </div>
          </Reveal>
        </section>

        <Reveal from="right" delay={200} threshold={0}>
          <section className="auth-panel relative w-full max-w-[450px] justify-self-end">
            <div className="auth-panel-topline" aria-hidden />
            <div className="p-7 sm:p-9">
            <div className="mb-8">
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-accent-2">{t("auth:login_kicker")}</div>
              <h2 className="mt-2 font-editorial text-[34px] font-normal leading-none text-text">{t("auth:login_workspace_access")}</h2>
              <p className="mt-3 text-[13px] leading-6 text-text-3">{t("auth:login_access_hint")}</p>
            </div>

            <form onSubmit={voidPromise(handleSubmit)} className="space-y-5">
              <div>
                <FieldLabel htmlFor="login-username" required>{t("auth:username")}</FieldLabel>
                <input id="login-username" type="text" autoComplete="username" spellCheck={false} value={username} onChange={(e) => setUsername(e.target.value)} className={`${INPUT_CLS} auth-input`} ref={usernameRef} required />
              </div>
              <div>
                <FieldLabel htmlFor="login-password" required>{t("auth:password")}</FieldLabel>
                <div className="relative">
                  <input id="login-password" type={showPassword ? "text" : "password"} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={`${INPUT_CLS} auth-input pr-11`} required />
                  <button type="button" className="auth-password-toggle" onClick={() => setShowPassword((value) => !value)} aria-label={t(showPassword ? "auth:hide_password" : "auth:show_password")}>
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {error && <p role="alert" aria-live="polite" className="auth-error text-sm text-warm-bright">{error}</p>}

              <button
                type="submit"
                disabled={loading}
                className={`${ACCENT_BTN_CLS} auth-submit w-full justify-center`}
                style={{ ...ACCENT_BUTTON_STYLE, fontSize: 15 }}
              >
                {loading && <Loader2 aria-hidden className="h-4 w-4 motion-safe:animate-spin" />}
                {loading ? t("auth:logging_in") : t("auth:login")}
              </button>

              {githubConfigured && (
                <>
                  <div className="auth-divider">
                    <span>{t("auth:login_or_github")}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      window.location.href = "/api/v1/auth/github/authorize";
                    }}
                    className="focus-ring flex w-full items-center justify-center gap-2.5 rounded-md border px-4 py-2.5 text-[14px] font-semibold transition-colors hover:border-hairline-strong"
                    style={{
                      borderColor: "var(--color-hairline-strong)",
                      background:
                        "color-mix(in oklab, var(--color-surface-2) 62%, transparent)",
                      color: "var(--color-text)",
                    }}
                  >
                    <svg viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor" aria-hidden="true">
                      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
                    </svg>
                    {t("auth:login_with_github")}
                  </button>
                </>
              )}
            </form>
          </div>
          </section>
        </Reveal>
      </main>
      <footer className="relative z-10 flex justify-between px-6 pb-5 font-mono text-[9px] uppercase tracking-[0.16em] text-text-4 lg:px-10">
        <span>{BRAND.name} / {BRAND.nameZh}</span>
      </footer>
    </div>
  );
}
