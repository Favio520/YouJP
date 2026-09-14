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

async function ensureOffscreen(): Promise<void> {
  // Solo puede existir un documento offscreen por extensión, así que hay que
  // comprobar antes de crearlo o la llamada falla.
  const existing = await chrome.runtime.getContexts({
    contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT],
  });
  if (existing.length > 0) return;

  await chrome.offscreen.createDocument({
    url: OFFSCREEN_PATH,
    reasons: [chrome.offscreen.Reason.USER_MEDIA],
    justification:
      'Capturar el audio de la pestaña y mantener la conexión con el servidor local de transcripción.',
  });
}

async function startCapture(tab: chrome.tabs.Tab): Promise<void> {
  if (!tab.id) return;

  await ensureOffscreen();

  // getMediaStreamId debe invocarse aquí, en el service worker, tras el gesto
  // del usuario. El identificador caduca en unos segundos si no se usa, así que
  // se manda inmediatamente.
  const streamId = await getMediaStreamId(tab.id);

  const info = await askTab(tab.id, { type: 'player.probe' } as never).catch(() => null);
  const { serverUrl = DEFAULT_SERVER_URL } = await chrome.storage.local.get('serverUrl');

  capture = { tabId: tab.id, videoId: info?.videoId ?? '' };

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

  await chrome.action.setBadgeText({ text: 'ON', tabId: tab.id });
  await chrome.action.setBadgeBackgroundColor({ color: '#24427C', tabId: tab.id });
}

async function stopCapture(): Promise<void> {
  const previous = capture;
  capture = null;
  await chrome.runtime.sendMessage({ type: 'capture.stop' } satisfies ExtensionMessage).catch(() => {});
  if (previous) {
    await chrome.action.setBadgeText({ text: '', tabId: previous.tabId }).catch(() => {});
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
  chrome.action.onClicked.addListener(async (tab) => {
    try {
      if (capture && capture.tabId === tab.id) {
        await stopCapture();
      } else {
        if (capture) await stopCapture();
        await startCapture(tab);
      }
    } catch (error) {
      console.error('[youjp] no se pudo alternar la captura', error);
      capture = null;
      if (tab.id) {
        chrome.tabs
          .sendMessage(tab.id, {
            type: 'status',
            status: 'error',
            detail: String(error),
          } satisfies ExtensionMessage)
          .catch(() => {});
      }
    }
  });

  // Encaminamiento offscreen -> pestaña. El offscreen no tiene chrome.tabs.
  chrome.runtime.onMessage.addListener((message: ExtensionMessage) => {
    if (!capture) return;
    if (
      message.type === 'status' ||
      message.type === 'subtitle.partial' ||
      message.type === 'subtitle.final' ||
      message.type === 'metrics' ||
      message.type === 'backend.error'
    ) {
      chrome.tabs.sendMessage(capture.tabId, message).catch(() => {
        // La pestaña puede estar navegando; no es un error que merezca ruido.
      });
    }
  });

  // Si la pestaña capturada se cierra o navega fuera, la captura ya no tiene
  // sentido: el streamId queda huérfano y el audio deja de llegar.
  chrome.tabs.onRemoved.addListener((tabId) => {
    if (capture?.tabId === tabId) void stopCapture();
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (capture?.tabId === tabId && changeInfo.status === 'loading') void stopCapture();
  });
});
