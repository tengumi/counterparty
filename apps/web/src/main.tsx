import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import './theme.css';

const root = document.getElementById('root');

if (!root) throw new Error('Application root is missing');

/**
 * Track the visual viewport so the layout follows the on-screen keyboard:
 * `--app-height` is the real usable height (shell binds to it) and
 * `data-keyboard` lets the docked composer drop its safe-area gap so it sits
 * flush against the keyboard.
 */
function syncViewport(): void {
  const vv = window.visualViewport;
  const height = Math.round(vv?.height ?? window.innerHeight);
  const overlap = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
  const el = document.documentElement;
  el.style.setProperty('--app-height', `${height}px`);
  el.dataset.keyboard = overlap > 80 ? 'open' : 'closed';
}

syncViewport();
window.visualViewport?.addEventListener('resize', syncViewport);
window.visualViewport?.addEventListener('scroll', syncViewport);
window.addEventListener('orientationchange', () => window.setTimeout(syncViewport, 250));

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <App requireSession />
    </BrowserRouter>
  </StrictMode>,
);
