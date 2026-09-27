/**
 * Service worker: coordina, no trabaja.
 *
 * Su único cometido es obtener el `streamId` de la pestaña —lo que exige un
 * gesto del usuario, por eso cuelga de `action.onClicked`— crear el documento
 * offscreen y encaminar mensajes hacia la pestaña. Ni audio ni sockets: este
 * contexto se termina por inactividad y se llevaría la sesión por delante.
 */

import { defineBackground } from '#imports';
import { DEFAULT_SERVER_URL, type ExtensionMessage } from '@/src/messages';
import { loadSettings, onSettingsChanged } from '@/src/settings';

const OFFSCREEN_PATH = 'offscreen.html';

/**
 * Envoltorio con callback en vez de la forma con promesa.
 *
 * `@types/chrome` no siempre declara la sobrecarga con promesa de este método
 * según la versión, y la forma con callback está soportada en todas. Además
 * deja recoger `chrome.runtime.lastError`, que es donde aparece el fallo cuando
 * la llamada no viene de un gesto del usuario.
 */
function getMediaStreamId(targetTabId: number): Promise<string> {
  return new Promise((resolve, reject) => {
    (chrome.tabCapture.getMediaStreamId as unknown as (
      options: { targetTabId: number },
      callback: (streamId: string) => void,
    ) => void)({ targetTabId }, (streamId) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message ?? 'tabCapture.getMediaStreamId falló'));
      } else {
        resolve(streamId);
      }
    });
  });
}

interface CaptureState {
  tabId: number;
  videoId: string;
}

let capture: CaptureState | null = null;
// The service worker may sleep during a 30-second reconnect delay.
const restored = chrome.storage.session.get('capture').then((state) => {
  capture = state.capture ?? null;
});

async function ensureOffscreen(): Promise<void> {
  // Solo puede existir un documento offscreen por extensión, así que hay que
  // comprobar antes de crearlo o la llamada falla.
  const existing = await chrome.runtime.getContexts({
    contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT],
  });
  if (existing.length === 0) {
    await chrome.offscreen.createDocument({
      url: OFFSCREEN_PATH,
      reasons: [chrome.offscreen.Reason.USER_MEDIA],
      justification:
        'Capturar el audio de la pestaña y mantener la conexión con el servidor local de transcripción.',
    });
  }

  // createDocument resuelve antes de que el módulo de la página termine de
  // cargar. Esperar su confirmación evita perder capture.start y consumir un
  // streamId de corta vida sin que nadie lo reciba.
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const response = await chrome.runtime
      .sendMessage({ type: 'offscreen.ping' } satisfies ExtensionMessage)
      .catch(() => null);
    if (response?.ready === true) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error('El componente de captura de YouJP no pudo iniciarse. Recarga la extensión.');
}

/**
 * Se asegura de que el content script está vivo en la pestaña.
 *
 * Al recargar la extensión, Chrome no vuelve a inyectar los content scripts en
 * las pestañas que ya estaban abiertas: solo entran al cargar la página. El
 * síntoma es de los peores, porque todo lo demás funciona — la captura arranca,
 * el audio llega al backend y se transcribe — pero no hay nadie que pinte el
 * overlay, así que parece que la extensión está rota.
 *
 * En vez de pedirle al usuario que recuerde recargar la pestaña, se inyecta a
 * mano cuando no contesta.
 */
async function ensureContentScript(tabId: number): Promise<any | null> {
  const probe = () => askTab(tabId, { type: 'player.probe' } as never);

  try {
    return await probe();
  } catch {
    // No está. Se inyecta leyendo la ruta del propio manifest, para que no se
    // quede desfasada si cambia la salida del empaquetado.
    const files = chrome.runtime.getManifest().content_scripts?.[0]?.js ?? [];
    if (files.length === 0) return null;
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files });
      return await probe();
    } catch (error) {
      console.warn('[youjp] no se pudo inyectar el overlay en la pestaña', error);
      return null;
    }
  }
}

async function startCapture(tab: chrome.tabs.Tab): Promise<void> {
  if (!tab.id) return;

  await ensureOffscreen();

  // getMediaStreamId debe invocarse aquí, en el service worker, tras el gesto
  // del usuario. El identificador caduca en unos segundos si no se usa, así que
  // se manda inmediatamente.
  const streamId = await getMediaStreamId(tab.id);

  const info = await ensureContentScript(tab.id);
  if (info === null) {
    // Sin overlay no hay nada que ver, así que capturar sería gastar GPU para
    // nadie. Mejor fallar aquí y decirlo que quedarse mudo.
    await chrome.action.setBadgeText({ text: '!', tabId: tab.id });
    await chrome.action.setBadgeBackgroundColor({ color: '#B8422B', tabId: tab.id });
    throw new Error(
      'No se pudo montar el overlay en esta pestaña. Recárgala (F5) e inténtalo de nuevo.',
    );
  }

  const { serverUrl = DEFAULT_SERVER_URL } = await chrome.storage.local.get('serverUrl');

  capture = { tabId: tab.id, videoId: info?.videoId ?? '' };
  await chrome.storage.session.set({ capture });
  await chrome.action.setBadgeText({ text: '...', tabId: tab.id });
  await chrome.action.setBadgeBackgroundColor({ color: '#24427C', tabId: tab.id });
  await chrome.action.setTitle({ title: 'YouJP: conectando', tabId: tab.id });

  await chrome.runtime.sendMessage({
    type: 'capture.start',
    streamId,
    tabId: tab.id,
    videoId: info?.videoId ?? '',
    url: tab.url ?? '',
    isLive: info?.isLive ?? false,
    mediaTimeMs: info?.mediaTimeMs ?? 0,
    serverUrl,
  } satisfies ExtensionMessage);

}

async function stopCapture(): Promise<void> {
  const previous = capture;
  capture = null;
  await chrome.storage.session.remove('capture');
  await chrome.runtime.sendMessage({ type: 'capture.stop' } satisfies ExtensionMessage).catch(() => {});
  if (previous) {
    await chrome.action.setBadgeText({ text: '', tabId: previous.tabId }).catch(() => {});
    await chrome.action
      .setTitle({ title: 'Activar subtítulos japoneses', tabId: previous.tabId })
      .catch(() => {});
    await chrome.tabs
      .sendMessage(previous.tabId, { type: 'status', status: 'idle' } satisfies ExtensionMessage)
      .catch(() => {});
  }
  await chrome.offscreen.closeDocument().catch(() => {});
}

function askTab(tabId: number, message: unknown): Promise<any> {
  return chrome.tabs.sendMessage(tabId, message);
}

export default defineBackground(() => {
  // El documento offscreen solo tiene chrome.runtime: el almacenamiento y
  // sus eventos se atienden aquí, también al despertar el service worker.
  onSettingsChanged((settings) => {
    chrome.runtime.sendMessage({ type: 'settings.changed', settings } satisfies ExtensionMessage)
      .catch(() => {});
  });

  chrome.action.onClicked.addListener(async (tab) => {
    try {
      await restored;
      if (capture && capture.tabId === tab.id) {
        await stopCapture();
      } else {
        if (capture) await stopCapture();
        await startCapture(tab);
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      console.error('[youjp] no se pudo alternar la captura', error);
      capture = null;
      await chrome.storage.session.remove('capture');
      if (tab.id) {
        // El overlay puede no existir justo cuando falla, así que el aviso va
        // también al icono: es el único sitio que siempre se ve.
        await chrome.action.setBadgeText({ text: '!', tabId: tab.id }).catch(() => {});
        await chrome.action
          .setBadgeBackgroundColor({ color: '#B8422B', tabId: tab.id })
          .catch(() => {});
        await chrome.action.setTitle({ title: `youjp: ${detail}`, tabId: tab.id }).catch(() => {});
        chrome.tabs
          .sendMessage(tab.id, {
            type: 'status',
            status: 'error',
            detail,
          } satisfies ExtensionMessage)
          .catch(() => {});
      }
    }
  });

  // Encaminamiento offscreen -> pestaña. El offscreen no tiene chrome.tabs.
  chrome.runtime.onMessage.addListener((message: ExtensionMessage, sender, respond) => {
    // Los content scripts siempre tienen sender.tab. Edge puede omitir
    // sender.url para documentos offscreen, así que no dependemos de esa URL.
    if (sender.id !== chrome.runtime.id || sender.tab) return;
    // Se solicitan antes de que exista una captura activa y después de montar
    // el audio, para recoger los cambios hechos durante el arranque.
    if (message.type === 'settings.get') {
      void loadSettings().then(respond);
      return true;
    }
    void restored.then(async () => {
      if (!capture || message.tabId !== capture.tabId) return;
      const tabId = capture.tabId;
      if (
        message.type === 'status' ||
        message.type === 'subtitle.partial' ||
        message.type === 'subtitle.final' ||
        message.type === 'subtitle.translation' ||
        message.type === 'subtitle.tokens' ||
        message.type === 'metrics' ||
        message.type === 'backend.error'
      ) {
        await chrome.tabs.sendMessage(tabId, message).catch(() => {});
        if (message.type === 'status' && capture?.tabId === tabId) {
          await chrome.action.setBadgeText({ tabId,
            text: message.status === 'running' ? 'ON' : message.status === 'idle' ? '' : message.status === 'error' ? '!' : '...' });
          await chrome.action.setTitle({ tabId,
            title: 'YouJP: ' + (message.detail || message.status) });
          if (message.status === 'error') {
            capture = null;
            await chrome.storage.session.remove('capture');
            await chrome.offscreen.closeDocument().catch(() => {});
          }
        }
      }
    }).catch(console.warn);
  });

  // Si la pestaña capturada se cierra o navega fuera, la captura ya no tiene
  // sentido: el streamId queda huérfano y el audio deja de llegar.
  chrome.tabs.onRemoved.addListener((tabId) => {
    void restored.then(() => { if (capture?.tabId === tabId) return stopCapture(); });
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    void restored.then(() => {
      if (capture?.tabId === tabId && changeInfo.status === 'loading') return stopCapture();
    });
  });
});
