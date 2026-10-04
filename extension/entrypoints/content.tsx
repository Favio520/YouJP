/**
 * Content script: monta el overlay y vigila el reproductor.
 *
 * No abre sockets ni toca audio. Pinta subtítulos y observa el reproductor.
 * El selector OCR se carga por separado, bajo demanda, en screen.content.ts.
 */

import { createShadowRootUi, defineContentScript } from '#imports';
import ReactDOM from 'react-dom/client';
import { Overlay } from '@/src/ui/Overlay';
import '@/src/ui/overlay.css';
import { findPlayerRoot, snapshot, watchPlayer } from '@/src/player';
import type { ExtensionMessage } from '@/src/messages';
import { loadSettings, onSettingsChanged } from '@/src/settings';
import { uiText, type UiLanguage } from '@/src/i18n';

export default defineContentScript({
  matches: ['*://www.youtube.com/*'],
  cssInjectionMode: 'ui',
  runAt: 'document_idle',

  async main(ctx) {
    // El service worker pregunta por el estado del reproductor antes de
    // arrancar la captura, para que la sesión nazca con la posición correcta.
    const onMessage = (message: unknown, _sender: chrome.runtime.MessageSender,
        respond: (response?: unknown) => void) => {
      if (typeof message === 'object' && message !== null &&
          'type' in message && message.type === 'player.probe') {
        respond(snapshot());
        return true;
      }
      return undefined;
    };
    chrome.runtime.onMessage.addListener(onMessage);

    const ui = await createShadowRootUi(ctx, {
      name: 'youjp-overlay',
      position: 'inline',
      // Anclado al contenedor del reproductor y no al body: así el overlay
      // sigue al vídeo en pantalla completa y en el modo teatro sin
      // recalcular nada.
      anchor: () => findPlayerRoot() ?? document.body,
      append: 'last',
      onMount(container) {
        const root = ReactDOM.createRoot(container);
        root.render(<Overlay />);
        return root;
      },
      onRemove(root) {
        root?.unmount();
      },
    });

    ui.mount();

    // Acceso a los ajustes en la barra del reproductor, junto al volumen.
    // YouTube reconstruye sus controles al cambiar de vídeo, así que el mismo
    // observador que remonta el overlay vuelve a colocar el botón si falta.
    let settingsButton: HTMLButtonElement | null = null;
    let language: UiLanguage = 'es';
    let settingsChanged = false;
    const updateButtonLabel = () => {
      if (!settingsButton) return;
      const label = uiText(language, 'Ajustes de YouJP');
      settingsButton.title = label;
      settingsButton.setAttribute('aria-label', label);
    };
    const stopSettings = onSettingsChanged((settings) => {
      settingsChanged = true;
      language = settings.settingsLanguage;
      updateButtonLabel();
    });
    void loadSettings().then((settings) => {
      if (!settingsChanged) language = settings.settingsLanguage;
      updateButtonLabel();
    });
    const ensureSettingsButton = () => {
      const player = findPlayerRoot();
      const controls = player?.querySelector<HTMLElement>('.ytp-left-controls');
      if (!controls || controls.querySelector('[data-youjp-settings]')) return;

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'ytp-button';
      button.dataset.youjpSettings = '';
      button.setAttribute('aria-haspopup', 'dialog');
      button.style.cssText = 'display:inline-grid;place-items:center;width:40px;min-width:40px;height:100%;padding:0;color:#c8e8d3;vertical-align:top;cursor:pointer;';
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      icon.setAttribute('viewBox', '0 0 24 24');
      icon.setAttribute('width', '22');
      icon.setAttribute('height', '22');
      icon.setAttribute('fill', 'none');
      icon.setAttribute('stroke', 'currentColor');
      icon.setAttribute('stroke-width', '1.5');
      icon.setAttribute('stroke-linecap', 'round');
      icon.setAttribute('aria-hidden', 'true');
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'M4 7h16M4 17h16M9 4v6m6 4v6');
      icon.append(path);
      button.append(icon);
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        window.dispatchEvent(new Event('youjp:toggle-settings'));
      });

      const volume = controls.querySelector('.ytp-volume-area');
      if (volume) volume.after(button);
      else controls.append(button);
      settingsButton = button;
      updateButtonLabel();
    };
    ensureSettingsButton();

    // Si YouTube reemplaza el reproductor al navegar entre vídeos, el overlay
    // se queda colgado de un nodo huérfano. Volver a montarlo es barato.
    const remount = new MutationObserver(() => {
      const player = findPlayerRoot();
      if (player && !player.querySelector('youjp-overlay')) {
        ui.remove();
        ui.mount();
      }
      ensureSettingsButton();
    });
    remount.observe(document.body, { childList: true, subtree: true });

    const send = (message: ExtensionMessage) => {
      chrome.runtime.sendMessage(message).catch(() => {
        // Sin captura activa no hay nadie escuchando. Es lo normal.
      });
    };

    let videoId = snapshot().videoId;
    const stopWatching = watchPlayer({
      onTick: (snap) => {
        if (snap.videoId !== videoId) {
          videoId = snap.videoId;
          window.dispatchEvent(new Event('youjp:video'));
        }
        send({
          type: 'player.tick',
          mediaTimeMs: snap.mediaTimeMs,
          paused: snap.paused,
          rate: snap.rate,
          videoId: snap.videoId,
          isLive: snap.isLive,
        });
      },
      onFlush: (reason, snap) => {
        window.dispatchEvent(new Event('youjp:flush'));
        send({ type: 'player.flush', reason, mediaTimeMs: snap.mediaTimeMs });
      },
      onRateWarning: (rate) => {
        window.dispatchEvent(new CustomEvent('youjp:rate', { detail: rate }));
      },
    });

    ctx.onInvalidated(() => {
      chrome.runtime.onMessage.removeListener(onMessage);
      stopWatching();
      stopSettings();
      remount.disconnect();
      ui.remove();
      settingsButton?.remove();
    });
  },
});
