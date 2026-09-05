export const viewports = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'tablet', width: 1024, height: 768 },
  { name: 'desktop', width: 1440, height: 900 },
] as const;

export type Viewport = (typeof viewports)[number];
export type DataSource = 'typed-fixtures' | 'live-rest' | 'design-reference';
export interface Check {
  name: string;
  viewport: string;
  source: DataSource;
  verdict: 'pass' | 'fail';
  details?: string;
}
export interface Capture {
  name: string;
  file: string;
  viewport: { width: number; height: number };
  source: DataSource;
  url: string;
}
export interface Manifest {
  scope: 'WEB-07';
  sourceSHA: string;
  sourceDirty: boolean;
  createdAt: string;
  browser: string;
  transport: 'Playwright connectOverCDP';
  baseURL: string;
  reference: { file: string; sha256: string; supportSHA256: string };
  checks: Check[];
  captures: Capture[];
  consoleErrors: string[];
  limitations: string[];
}

export const matrix = {
  screenshots: {
    reference: ['S1/S2 at all three widths', 'materials at desktop/mobile'],
    allViewports: ['s1-populated', 's2-conversation', 'materials'],
    desktopAndMobile: ['report', 'evidence'],
    desktop: ['s1-empty', 's1-loading', 's1-error'],
    mobile: ['long-name', 'chat-switcher'],
  },
  assertions: [
    'S1 empty-send disabled, examples insert without posting, Shift+Enter, failed submit retains draft',
    'S2 independent feed scroll, pinned composer, materials open/back/close preserves draft and scroll',
    'Keyboard focus return, visible focus, mobile key controls >=44px, no horizontal overflow',
    'Report pinned facts and source navigation; missing/empty/unavailable distinct',
    'Chat switch and reload restore draft/scroll, 200% text zoom readability',
    'Separate live REST create/rename/add/remove/reload and partial not_found via browser',
  ],
};
