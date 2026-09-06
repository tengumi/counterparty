export interface UiApiConfig {
  readonly baseUrl: string;
}

function normalizeBaseUrl(value: string | undefined): string {
  if (!value) return '';
  return value.replace(/\/$/, '');
}

/** Empty means same-origin; Vite proxies `/api/v1` to ui_api during local development. */
export const uiApiConfig: UiApiConfig = {
  baseUrl: normalizeBaseUrl(import.meta.env.VITE_UI_API_BASE_URL as string | undefined),
};
