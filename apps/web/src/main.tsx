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
  const el = document.documentElement;
  if (!vv) {
    el.dataset.keyboard = 'closed';
    return;
  }
  const overlap = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
  const open = overlap > 80;
  el.dataset.keyboard = open ? 'open' : 'closed';
  if (open) {
    // Pin the shell to the visible strip: Safari also scrolls the page up on
    // focus, so we size to the visual viewport and undo that scroll offset.
    el.style.setProperty('--app-height', `${Math.round(vv.height)}px`);
    el.style.setProperty('--app-offset', `${Math.round(vv.offsetTop)}px`);
  } else {
    el.style.removeProperty('--app-height');
    el.style.removeProperty('--app-offset');
  }
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
