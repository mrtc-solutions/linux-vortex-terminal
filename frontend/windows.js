/* Window controls shared by Electron's native frame and VORTEX in-app windows. */
(function (root) {
  'use strict';

  const NORMAL = 'normal';
  const MINIMIZED = 'minimized';
  const MAXIMIZED = 'maximized';

  function nextWindowState(current, action) {
    current = [NORMAL, MINIMIZED, MAXIMIZED].includes(current) ? current : NORMAL;
    if (action === 'minimize') return current === MINIMIZED ? NORMAL : MINIMIZED;
    if (action === 'maximize') return current === MAXIMIZED ? NORMAL : MAXIMIZED;
    if (action === 'close') return 'closed';
    return current;
  }

  function stateOf(element) {
    return element?.dataset?.windowState || NORMAL;
  }

  function updateControlLabels(host, state, selector) {
    host.querySelectorAll(selector).forEach(button => {
      const action = button.dataset.surfaceAction || button.dataset.terminalWindowAction;
      const icon = button.querySelector('[aria-hidden="true"]');
      if (action === 'minimize') {
        const restore = state === MINIMIZED;
        button.setAttribute('aria-label', restore ? 'Restore window' : 'Minimize window');
        button.title = restore ? 'Restore' : 'Minimize';
        if (icon) icon.textContent = restore ? '▢' : '—';
      } else if (action === 'maximize') {
        const restore = state === MAXIMIZED;
        button.setAttribute('aria-label', restore ? 'Restore window' : 'Maximize window');
        button.title = restore ? 'Restore' : 'Maximize';
        button.setAttribute('aria-pressed', String(restore));
        if (icon) icon.textContent = restore ? '❐' : '□';
      }
    });
  }

  function applySurfaceState(surface, state) {
    const effective = [NORMAL, MINIMIZED, MAXIMIZED].includes(state) ? state : NORMAL;
    surface.dataset.windowState = effective;
    surface.classList.toggle('is-minimized', effective === MINIMIZED);
    surface.classList.toggle('is-maximized', effective === MAXIMIZED);
    const dialog = surface.querySelector('[role="dialog"]');
    if (dialog) dialog.setAttribute('aria-modal', String(effective !== MINIMIZED));
    updateControlLabels(surface, effective, '[data-surface-action]');
  }

  function showSurface(surfaceOrId) {
    const doc = root.document;
    const surface = typeof surfaceOrId === 'string' ? doc?.getElementById(surfaceOrId) : surfaceOrId;
    if (!surface) return false;
    if (surface.hidden) surface._vortexReturnFocus = doc.activeElement;
    applySurfaceState(surface, NORMAL);
    surface.hidden = false;
    const titlebar = surface.querySelector('.surface-titlebar');
    if (titlebar) titlebar.setAttribute('tabindex', '-1');
    root.requestAnimationFrame?.(() => titlebar?.focus({ preventScroll: true }));
    return true;
  }

  function closeSurface(surface) {
    if (!surface) return;
    applySurfaceState(surface, NORMAL);
    surface.hidden = true;
    const returnFocus = surface._vortexReturnFocus;
    if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus({ preventScroll: true });
    surface._vortexReturnFocus = null;
  }

  function performSurfaceAction(surface, action) {
    const next = nextWindowState(stateOf(surface), action);
    if (next === 'closed') closeSurface(surface);
    else applySurfaceState(surface, next);
  }

  function bindSurfaceWindows(doc) {
    doc.querySelectorAll('[data-surface-window]').forEach(surface => {
      applySurfaceState(surface, stateOf(surface));
      surface.querySelectorAll('[data-surface-action]').forEach(button => {
        button.addEventListener('click', () => performSurfaceAction(surface, button.dataset.surfaceAction));
      });
      const titlebar = surface.querySelector('.surface-titlebar');
      titlebar?.addEventListener('dblclick', event => {
        if (!event.target.closest('button, input, select, a')) performSurfaceAction(surface, 'maximize');
      });
    });
  }

  function applyTerminalState(terminal, state) {
    const effective = [NORMAL, MINIMIZED, MAXIMIZED].includes(state) ? state : NORMAL;
    terminal.dataset.windowState = effective;
    terminal.classList.toggle('is-minimized', effective === MINIMIZED);
    terminal.classList.toggle('is-maximized', effective === MAXIMIZED);
    updateControlLabels(terminal, effective, '[data-terminal-window-action]');
    root.requestAnimationFrame?.(() => {
      if (root.Event && root.dispatchEvent) root.dispatchEvent(new root.Event('resize'));
    });
  }

  function performTerminalAction(terminal, action) {
    if (action === 'close') {
      applyTerminalState(terminal, NORMAL);
      if (typeof root.setView === 'function') root.setView('overview');
      if (typeof root.toast === 'function') root.toast('Terminal window closed. Live PTY sessions remain available.');
      return;
    }
    applyTerminalState(terminal, nextWindowState(stateOf(terminal), action));
  }

  function bindTerminalWindow(doc) {
    const terminal = doc.querySelector('[data-terminal-window]');
    if (!terminal) return;
    applyTerminalState(terminal, stateOf(terminal));
    terminal.querySelectorAll('[data-terminal-window-action]').forEach(button => {
      button.addEventListener('click', () => performTerminalAction(terminal, button.dataset.terminalWindowAction));
    });
    terminal.querySelector('.terminal-toolbar')?.addEventListener('dblclick', event => {
      if (!event.target.closest('button, input, select, a')) performTerminalAction(terminal, 'maximize');
    });
  }

  function applyNativeState(doc, state) {
    const maximize = doc.querySelector('[data-native-window-action="toggleMaximize"]');
    if (maximize) {
      const restored = state?.maximized === true || state?.fullScreen === true;
      maximize.setAttribute('aria-label', restored ? 'Restore application window' : 'Maximize application window');
      maximize.title = restored ? 'Restore' : 'Maximize';
      maximize.setAttribute('aria-pressed', String(restored));
      const icon = maximize.querySelector('[aria-hidden="true"]');
      if (icon) icon.textContent = restored ? '❐' : '□';
      maximize.disabled = state?.maximizable === false;
    }
    const minimize = doc.querySelector('[data-native-window-action="minimize"]');
    if (minimize) minimize.disabled = state?.minimizable === false;
    const close = doc.querySelector('[data-native-window-action="close"]');
    if (close) close.disabled = state?.closable === false;
  }

  function bindNativeWindow(doc) {
    const bridge = root.vortexWindow;
    const titlebar = doc.getElementById('app-titlebar');
    if (!bridge || !titlebar) return;
    doc.body.classList.add('electron-shell');
    titlebar.querySelectorAll('[data-native-window-action]').forEach(button => {
      button.addEventListener('click', () => {
        const action = button.dataset.nativeWindowAction;
        if (typeof bridge[action] === 'function') bridge[action]();
      });
    });
    titlebar.querySelector('.app-titlebar-drag')?.addEventListener('dblclick', event => {
      if (!event.target.closest('button')) bridge.toggleMaximize();
    });
    bridge.onStateChange?.(state => applyNativeState(doc, state));
    Promise.resolve(bridge.getState?.()).then(state => applyNativeState(doc, state)).catch(() => {});
  }

  function bindEscapeKey(doc) {
    doc.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      const surfaces = Array.from(doc.querySelectorAll('[data-surface-window]')).filter(surface => !surface.hidden);
      if (surfaces.length) {
        closeSurface(surfaces[surfaces.length - 1]);
        event.preventDefault();
        return;
      }
      const terminal = doc.querySelector('[data-terminal-window].is-maximized');
      if (terminal) {
        applyTerminalState(terminal, NORMAL);
        event.preventDefault();
      }
    });
  }

  function init(doc = root.document) {
    if (!doc) return;
    bindNativeWindow(doc);
    bindSurfaceWindows(doc);
    bindTerminalWindow(doc);
    bindEscapeKey(doc);
  }

  root.VortexWindows = Object.freeze({
    applySurfaceState,
    closeSurface,
    init,
    nextWindowState,
    showSurface
  });

  if (root.document) root.addEventListener('DOMContentLoaded', () => init(root.document));
})(window);
