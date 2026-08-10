import { useState, type FormEvent } from "react";
import { ArrowUpRight, Eye, EyeOff, Film, Loader2, Sparkles } from "lucide-react";
import { useAutoFocus } from "@/hooks/useAutoFocus";
import { errMsg, voidPromise } from "@/utils/async";
import { useLocation, useSearch } from "wouter";
import { useTranslation } from "react-i18next";
import { useAuthStore } from "@/stores/auth-store";
import { safeReturnPath } from "@/utils/safe-url";
import { BRAND } from "@/branding";
import type { LoginResponse, ErrorResponse } from "@/api";
import { FieldLabel } from "@/components/ui/FieldLabel";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import {
  ACCENT_BTN_CLS,
  ACCENT_BUTTON_STYLE,
  INPUT_CLS,
} from "@/components/ui/darkroom-tokens";

export function LoginPage() {
  const { t, i18n } = useTranslation(["common", "auth"]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [, setLocation] = useLocation();
  const search = useSearch();
  const login = useAuthStore((s) => s.login);
  const usernameRef = useAutoFocus<HTMLInputElement>();

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
      login(data.access_token, username);
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
        <div className="flex items-center gap-4">
          <span className="hidden items-center gap-2 font-mono text-[10px] uppercase tracking-[0.16em] text-good sm:inline-flex">
            <span className="auth-status-dot" />
            {t("auth:login_system_status")}
          </span>
          <ThemeToggle />
        </div>
      </header>

      <main className="auth-layout relative z-10 mx-auto grid w-full max-w-[1240px] gap-10 px-6 pb-10 pt-6 lg:grid-cols-[1.08fr_0.82fr] lg:items-center lg:px-10 lg:pb-20 lg:pt-12">
        <section className="auth-showcase min-w-0">
          <div className="mb-5 flex items-center gap-3 font-mono text-[10px] font-semibold uppercase tracking-[0.17em] text-accent-2">
            <span className="auth-kicker-line" />
            {t("auth:login_kicker")}
          </div>
          <h1 className="auth-title max-w-[720px] text-balance font-editorial text-[clamp(3.2rem,6.8vw,6.8rem)] font-normal leading-[0.9] tracking-[-0.035em] text-text">
            {t("auth:login_hero_title")}
          </h1>
          <p className="mt-7 max-w-[560px] text-[15px] leading-7 text-text-2 lg:text-[17px]">{t("auth:login_hero_body")}</p>

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

          <div className="auth-metrics mt-8 grid max-w-[620px] grid-cols-3">
            {["login_metric_worlds", "login_metric_shots", "login_metric_render"].map((key, index) => (
              <div key={key} className="auth-metric">
                <div className="font-mono text-[9px] uppercase tracking-[0.14em] text-text-4">{t(`auth:${key}`)}</div>
                <div className="mt-2 font-editorial text-[27px] text-text">{["01", "08", "∞"][index]}</div>
              </div>
            ))}
          </div>
        </section>

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

              <button type="submit" disabled={loading} className={`${ACCENT_BTN_CLS} auth-submit w-full justify-between`} style={ACCENT_BUTTON_STYLE}>
                <span className="flex items-center gap-2">{loading && <Loader2 aria-hidden className="h-4 w-4 motion-safe:animate-spin" />}{loading ? t("auth:logging_in") : t("auth:login")}</span>
                {!loading && <ArrowUpRight aria-hidden className="h-4 w-4" />}
              </button>
            </form>

            <div className="auth-divider"><span>{t("auth:login_admin_note")}</span></div>
            <a className="auth-request-button" href="mailto:admin@shotwise.local">{t("auth:login_contact_admin")}<ArrowUpRight aria-hidden className="h-3.5 w-3.5" /></a>
          </div>
        </section>
      </main>
      <footer className="relative z-10 flex justify-between px-6 pb-5 font-mono text-[9px] uppercase tracking-[0.16em] text-text-4 lg:px-10">
        <span>{BRAND.name} / {t("auth:login_footer")}</span>
        <span className="hidden sm:inline">{t("auth:login_build")}</span>
      </footer>
    </div>
  );
}
