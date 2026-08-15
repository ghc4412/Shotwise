/**
 * 设置页返回路径的 sessionStorage 存取。
 *
 * 设置入口（UserMenu / 系统设置页返回按钮）共用同一 key 与消费逻辑；
 * 独立成模块避免布局组件与页面组件互相 import 造成循环依赖。
 */

const SETTINGS_RETURN_TO_KEY = "settings:returnTo";

/** 设置入口点击前调用，记录返回目标（如从项目剪辑台进入后返回原地）。只接受应用内部路径，避免 open redirect 风险。 */
export function rememberSettingsReturnTo(pathname: string) {
  if (pathname.startsWith("/app/")) {
    sessionStorage.setItem(SETTINGS_RETURN_TO_KEY, pathname);
  }
}

/** 设置页返回按钮消费记录；一次性读取并清除，非法路径回退 null 由调用方兜底。 */
export function consumeSettingsReturnTo(): string | null {
  const returnTo = sessionStorage.getItem(SETTINGS_RETURN_TO_KEY);
  sessionStorage.removeItem(SETTINGS_RETURN_TO_KEY);
  return returnTo;
}
