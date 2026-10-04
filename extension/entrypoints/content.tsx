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
import { INITIAL_UI_STATE, UI_STATE_EVENT, type UiState } from '@/src/ui/uiState';
import { buildSvg, ICONS, type IconShape } from '@/src/ui/iconShapes';

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
    let language: UiLanguage = 'es';
    let settingsChanged = false;
    let uiState: UiState = INITIAL_UI_STATE;

    const RING = 2 * Math.PI * 9;
    const badge = (fill: string, mark: string, markColor: string): IconShape[] => [
      { tag: 'circle', attrs: { cx: 19, cy: 5.5, r: 4.2, fill, stroke: '#0e1522', strokeWidth: 1.2 } },
      { tag: 'path', attrs: { d: mark, stroke: markColor, strokeWidth: 1.6, fill: 'none' } },
    ];

    /** Dibujo, texto y color del botón de traducir según el estado del vídeo.
     *  `key` identifica el aspecto: si no cambia, no se toca el DOM. */
    const translateView = (video: UiState['video']) => {
      const text = (es: string, en: string) => uiText(language, es, en);
      const percent = Math.round(video.progress * 100);
      let shapes: IconShape[] = ICONS.translate;
      let label = text('Traducir el vídeo completo', 'Translate the whole video');
      let color = '#c8e8d3';
      let pressed: boolean | null = null;
      let key = 'none';
      if (video.phase === 'working') {
        // Anillo que se llena con el progreso; sin progreso aún, gira.
        const arc: IconShape = video.progress > 0.02
          ? { tag: 'circle', attrs: { cx: 12, cy: 12, r: 9, stroke: '#c8e8d3', strokeWidth: 2.4,
            strokeDasharray: `${(RING * video.progress).toFixed(1)} ${RING.toFixed(1)}`, transform: 'rotate(-90 12 12)', fill: 'none' } }
          : { tag: 'circle', attrs: { cx: 12, cy: 12, r: 9, stroke: '#c8e8d3', strokeWidth: 2.4,
            strokeDasharray: '14 43', fill: 'none' }, spin: true };
        shapes = [
          { tag: 'circle', attrs: { cx: 12, cy: 12, r: 9, strokeWidth: 2.4, opacity: 0.28, fill: 'none' } },
          arc,
          { tag: 'rect', attrs: { x: 9.2, y: 9.2, width: 5.6, height: 5.6, rx: 1.3 }, tone: 'solid' },
        ];
        label = percent > 0
          ? text(`Traduciendo el vídeo… ${percent} %. Pulsa para detener`, `Translating the video… ${percent}%. Click to stop`)
          : text('Preparando la traducción. Pulsa para detener', 'Getting the translation ready. Click to stop');
        color = '#e6f4ec';
        key = `work:${percent > 0 ? percent : 'spin'}`;
      } else if (video.phase === 'ready' && video.enabled) {
        shapes = [...ICONS.translate, ...badge('#7ed6a0', 'm17.2 5.6 1.3 1.3 2.3-2.5', '#0d2a1b')];
        label = text('Vídeo traducido, subtítulos encendidos. Pulsa para apagarlos', 'Video translated, subtitles on. Click to turn them off');
        pressed = true;
        key = 'on';
      } else if (video.phase === 'ready') {
        shapes = [
          ...ICONS.translate.map((shape) => ({ ...shape, attrs: { ...shape.attrs, opacity: 0.55 } })),
          { tag: 'path', attrs: { d: 'M4 20 20 4', strokeWidth: 2 } },
        ];
        label = text('Subtítulos apagados. Pulsa para encenderlos', 'Subtitles off. Click to turn them on');
        pressed = false;
        key = 'off';
      } else if (video.phase === 'error') {
        shapes = [...ICONS.translate, ...badge('#ffb4a8', 'M19 3.6v2.2M19 7.4v.1', '#4a160e')];
        label = text('No se pudo traducir. Pulsa para reintentar', 'Could not translate. Click to try again');
        color = '#ffd1ca';
        key = 'error';
      }
      return { shapes, label, color, pressed, key: `${key}|${language}` };
    };

    interface PlayerButton {
      attr: string; event: string; element: HTMLButtonElement | null;
      icon: IconShape[]; label: string; state: 'settings' | 'translate';
      /** Lo último que se pintó: sin esto, repintar dispara el observador y entra en bucle. */
      painted?: string;
    }
    const buttons: PlayerButton[] = [
      { attr: 'youjpSettings', icon: ICONS.settings, label: 'Ajustes de YouJP',
        event: 'youjp:toggle-settings', element: null, state: 'settings' },
      // Traduce el vídeo entero de antemano (no es para directos).
      { attr: 'youjpPrepare', icon: ICONS.translate, label: 'Traducir el vídeo completo',
        event: 'youjp:prepare-video', element: null, state: 'translate' },
    ];

    const paintButtons = () => {
      for (const item of buttons) {
        const element = item.element;
        if (!element) continue;
        if (item.state === 'translate') {
          const view = translateView(uiState.video);
          if (item.painted === view.key) continue;
          item.painted = view.key;
          element.replaceChildren(buildSvg(view.shapes));
          element.title = view.label;
          element.setAttribute('aria-label', view.label);
          element.style.color = view.color;
          if (view.pressed === null) element.removeAttribute('aria-pressed');
          else element.setAttribute('aria-pressed', String(view.pressed));
          element.dataset.youjpState = uiState.video.phase;
        } else {
          const label = uiText(language, item.label, 'YouJP settings');
          const key = `${language}|${uiState.settingsOpen}`;
          if (item.painted === key) continue;
          item.painted = key;
          element.title = label;
          element.setAttribute('aria-label', label);
          element.setAttribute('aria-pressed', String(uiState.settingsOpen));
          // Abierto: se marca con un fondo lila para saber que el panel es suyo.
          element.style.background = uiState.settingsOpen ? 'rgba(185,162,244,.3)' : '';
          element.style.color = uiState.settingsOpen ? '#e6dcff' : '#c8e8d3';
        }
      }
    };
    const onUiState = (event: Event) => {
      uiState = (event as CustomEvent<UiState>).detail;
      paintButtons();
    };
    window.addEventListener(UI_STATE_EVENT, onUiState);

    const stopSettings = onSettingsChanged((settings) => {
      settingsChanged = true;
      language = settings.settingsLanguage;
      paintButtons();
    });
    void loadSettings().then((settings) => {
      if (!settingsChanged) language = settings.settingsLanguage;
      paintButtons();
    });
    const ensureButtons = () => {
      const player = findPlayerRoot();
      const controls = player?.querySelector<HTMLElement>('.ytp-left-controls');
      if (!controls) return;
      // A la derecha del minutero (0:42 / 5:10); si YouTube no lo muestra, junto al volumen.
      let anchor: Element | null = controls.querySelector('.ytp-time-display')
        ?? controls.querySelector('.ytp-volume-area');
      for (const item of buttons) {
        const attribute = item.attr.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
        const existing = controls.querySelector(`[data-${attribute}]`);
        if (existing) {
          item.element = existing as HTMLButtonElement;
          // Si YouTube recolocó los controles, vuelve a ponerse tras el minutero.
          if (anchor && anchor.nextElementSibling !== existing && anchor !== existing) anchor.after(existing);
          anchor = existing;
          continue;
        }
        item.painted = undefined;

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ytp-button';
        button.dataset[item.attr] = '';
        button.style.cssText = 'display:inline-grid;place-items:center;width:40px;min-width:40px;height:100%;padding:0;color:#c8e8d3;vertical-align:top;cursor:pointer;border-radius:8px;';
        button.append(buildSvg(item.icon));
        button.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          window.dispatchEvent(new Event(item.event));
        });

        if (anchor) anchor.after(button);
        else controls.append(button);
        anchor = button;
        item.element = button;
      }
      paintButtons();
    };
    ensureButtons();

    // Si YouTube reemplaza el reproductor al navegar entre vídeos, el overlay
    // se queda colgado de un nodo huérfano. Volver a montarlo es barato.
    const remount = new MutationObserver(() => {
      const player = findPlayerRoot();
      if (player && !player.querySelector('youjp-overlay')) {
        ui.remove();
        ui.mount();
      }
      ensureButtons();
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
      window.removeEventListener(UI_STATE_EVENT, onUiState);
      for (const item of buttons) item.element?.remove();
    });
  },
});
