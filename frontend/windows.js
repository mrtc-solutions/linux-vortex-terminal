/* Window controls shared by Electron's native frame and VORTEX in-app windows.
   Pop-up surfaces can be open at the same time: the front one tracks focus,
   minimized ones wait in the tray, and every surface keeps its own state. */
(function (root) {
  'use strict';

  const NORMAL = 'normal';
  const MINIMIZED = 'minimized';
  const MAXIMIZED = 'maximized';
  let zCounter = 40;

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

  function labelOf(surface) {
    return surface.dataset.surfaceLabel || surface.querySelector('.surface-titlebar strong, .surface-titlebar h2, .surface-titlebar .panel-kicker')?.textContent?.trim() || 'Window';
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

  function tray() {
    return root.document?.getElementById('window-tray') || null;
  }

  function renderTray(doc = root.document) {
    const host = tray();
    if (!host) return;
    const minimized = Array.from(doc.querySelectorAll('[data-surface-window]'))
      .filter(surface => !surface.hidden && stateOf(surface) === MINIMIZED);
    host.innerHTML = minimized.map(surface =>
      `<button type="button" class="tray-chip" data-tray-restore="${escAttr(surface.id)}"><span class="tray-led"></span>${escText(labelOf(surface))}</button>`
    ).join('');
    host.hidden = !minimized.length;
    host.querySelectorAll('[data-tray-restore]').forEach(chip => {
      chip.addEventListener('click', () => {
        const surface = doc.getElementById(chip.dataset.trayRestore);
        if (surface) applySurfaceState(surface, NORMAL);
      });
    });
  }

  const escText = (value) => String(value || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const escAttr = escText;

  function bringToFront(surface) {
    zCounter += 1;
    surface.style.zIndex = String(zCounter);
  }

  function frontSurface(doc = root.document) {
    const open = Array.from(doc.querySelectorAll('[data-surface-window]')).filter(surface => !surface.hidden);
    return open.sort((a, b) => Number(b.style.zIndex || 0) - Number(a.style.zIndex || 0))[0] || null;
  }

  function applySurfaceState(surface, state) {
    const effective = [NORMAL, MINIMIZED, MAXIMIZED].includes(state) ? state : NORMAL;
    surface.dataset.windowState = effective;
    surface.classList.toggle('is-minimized', effective === MINIMIZED);
    surface.classList.toggle('is-maximized', effective === MAXIMIZED);
    const dialog = surface.querySelector('[role="dialog"]');
    if (dialog) dialog.setAttribute('aria-modal', String(effective !== MINIMIZED));
    updateControlLabels(surface, effective, '[data-surface-action]');
    if (effective !== MINIMIZED) bringToFront(surface);
    renderTray(surface.ownerDocument || root.document);
  }

  function showSurface(surfaceOrId, doc = root.document) {
    const surface = typeof surfaceOrId === 'string' ? doc?.getElementById(surfaceOrId) : surfaceOrId;
    if (!surface) return false;
    if (surface.hidden) surface._vortexReturnFocus = doc.activeElement;
    if (stateOf(surface) === MINIMIZED) applySurfaceState(surface, NORMAL);
    else if (!surface.hidden) bringToFront(surface);
    if (surface.hidden) surface.hidden = false;
    const titlebar = surface.querySelector('.surface-titlebar');
    if (titlebar) titlebar.setAttribute('tabindex', '-1');
    root.requestAnimationFrame?.(() => titlebar?.focus({ preventScroll: true }));
    return true;
  }

  function closeSurface(surface, doc = root.document) {
    if (!surface) return;
    applySurfaceState(surface, NORMAL);
    surface.hidden = true;
    renderTray(doc || surface.ownerDocument || root.document);
    const returnFocus = surface._vortexReturnFocus;
    if (returnFocus && typeof returnFocus.focus === 'function' && doc.contains?.(returnFocus)) returnFocus.focus({ preventScroll: true });
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
    const host = tray();
    if (host) {
      host.addEventListener('click', event => {
        const chip = event.target.closest('[data-tray-restore]');
        if (!chip) return;
        const surface = doc.getElementById(chip.dataset.trayRestore);
        if (surface) applySurfaceState(surface, NORMAL);
      });
    }
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

  function focusTrapTarget(focusables, activeElement, shiftKey) {
    if (!focusables.length) return null;
    const index = focusables.indexOf(activeElement);
    if (index < 0) return shiftKey ? focusables[focusables.length - 1] : focusables[0];
    if (shiftKey && index === 0) return focusables[focusables.length - 1];
    if (!shiftKey && index === focusables.length - 1) return focusables[0];
    return null;
  }

  function bindDialogKeys(doc) {
    doc.addEventListener('keydown', event => {
      const activeSurface = frontSurface(doc);
      if (event.key === 'Tab' && activeSurface && stateOf(activeSurface) !== MINIMIZED) {
        const selector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
        const focusables = Array.from(activeSurface.querySelectorAll(selector)).filter(element => !element.hidden && element.getAttribute('aria-hidden') !== 'true' && (!element.getClientRects || element.getClientRects().length > 0));
        if (!focusables.length) {
          activeSurface.querySelector('.surface-titlebar, [role="dialog"]')?.focus({ preventScroll: true });
          event.preventDefault();
          return;
        }
        const target = focusTrapTarget(focusables, doc.activeElement, event.shiftKey);
        if (target) {
          target.focus({ preventScroll: true });
          event.preventDefault();
        }
        return;
      }
      if (event.key !== 'Escape') return;
      if (activeSurface) {
        closeSurface(activeSurface, doc);
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
    bindDialogKeys(doc);
  }

  root.VortexWindows = Object.freeze({
    applySurfaceState,
    closeSurface,
    focusTrapTarget,
    frontSurface,
    init,
    labelOf,
    nextWindowState,
    renderTray,
    showSurface
  });

  if (root.document) root.addEventListener('DOMContentLoaded', () => init(root.document));
})(window);
