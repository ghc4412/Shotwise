const LAST_OPENED_PROJECT_KEY = "shotwise:lastOpenedProject";

export function getLastOpenedProjectName(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(LAST_OPENED_PROJECT_KEY);
  } catch {
    return null;
  }
}

export function rememberLastOpenedProject(name: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LAST_OPENED_PROJECT_KEY, name);
  } catch {
    // The lobby can still fall back to project timestamps when storage is unavailable.
  }
}
