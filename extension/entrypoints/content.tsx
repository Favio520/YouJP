/**
 * Content script: monta el overlay y vigila el reproductor.
 *
 * No abre sockets ni toca audio. Solo dos cosas: pintar lo que llega y avisar
 * de lo que hace el reproductor.
 */

import { createShadowRootUi, defineContentScript } from '#imports';
import ReactDOM from 'react-dom/client';
import { Overlay } from '@/src/ui/Overlay';
import '@/src/ui/overlay.css';
import { findPlayerRoot, snapshot, watchPlayer } from '@/src/player';
import type { ExtensionMessage } from '@/src/messages';

export default defineContentScript({
  matches: ['*://www.youtube.com/*'],
  cssInjectionMode: 'ui',
  runAt: 'document_idle',

  async main(ctx) {
    // El service worker pregunta por el estado del reproductor antes de
    // arrancar la captura, para que la sesión nazca con la posición correcta.
    chrome.runtime.onMessage.addListener((message: any, _sender, respond) => {
      if (message?.type === 'player.probe') {
        respond(snapshot());
        return true;
      }
      return undefined;
    });

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

    // Si YouTube reemplaza el reproductor al navegar entre vídeos, el overlay
    // se queda colgado de un nodo huérfano. Volver a montarlo es barato.
    const remount = new MutationObserver(() => {
      const player = findPlayerRoot();
      if (player && !player.querySelector('youjp-overlay')) {
        ui.remove();
        ui.mount();
      }
    });
    remount.observe(document.body, { childList: true, subtree: true });

    const send = (message: ExtensionMessage) => {
      chrome.runtime.sendMessage(message).catch(() => {
        // Sin captura activa no hay nadie escuchando. Es lo normal.
      });
    };

    const stopWatching = watchPlayer({
      onTick: (snap) => {
        send({
          type: 'player.tick',
          mediaTimeMs: snap.mediaTimeMs,
          paused: snap.paused,
          rate: snap.rate,
          videoId: snap.videoId,
        });
      },
      onFlush: (reason, snap) => {
        send({ type: 'player.flush', reason, mediaTimeMs: snap.mediaTimeMs });
      },
      onRateWarning: (rate) => {
        window.dispatchEvent(new CustomEvent('youjp:rate', { detail: rate }));
      },
    });

    ctx.onInvalidated(() => {
      stopWatching();
      remount.disconnect();
    });
  },
});
