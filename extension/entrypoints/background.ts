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
import type { PlayerSnapshot } from '@/src/player';
import { captureAndTranslate, retryScreenTranslation, supportsScreenCapture, validSelection } from '@/src/screenCapture';
import { uiText, type UiLanguage } from '@/src/i18n';
import { callVideoApi, isVideoRequest } from '@/src/video';

const OFFSCREEN_PATH = 'offscreen.html';
let uiLanguage: UiLanguage = 'es';
let languageChanged = false;
const t = (value: string) => uiText(uiLanguage, value);

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
      } else if (!streamId) {
        reject(new Error('Chrome no devolvió un identificador de captura válido'));
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
let captureCommands: Promise<void> = Promise.resolve();

// Todos los cambios de captura comparten una cola: dos clics rápidos no deben
// crear dos documentos ni dejar un inicio pendiente después de detenerlo.
function queueCapture(command: () => Promise<void>): Promise<void> {
  const pending = captureCommands.then(command);
  captureCommands = pending.catch(() => {});
  return pending;
}
// El service worker puede dormirse durante los 30 segundos de reconexión.
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
function isPlayerSnapshot(value: unknown): value is PlayerSnapshot {
  if (typeof value !== 'object' || value === null) return false;
  const item = value as Record<string, unknown>;
  return typeof item.videoId === 'string' && typeof item.mediaTimeMs === 'number' &&
    typeof item.isLive === 'boolean' && typeof item.paused === 'boolean' &&
    typeof item.rate === 'number' && Number.isFinite(item.mediaTimeMs) &&
    item.mediaTimeMs >= 0 && Number.isFinite(item.rate) && item.rate > 0;
}

async function ensureContentScript(tabId: number): Promise<PlayerSnapshot | null> {
  const probe = async (): Promise<PlayerSnapshot> => {
    const response: unknown = await chrome.tabs.sendMessage(tabId, { type: 'player.probe' });
    if (!isPlayerSnapshot(response)) throw new Error('Respuesta no válida del reproductor');
    return response;
  };

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
  if (tab.id === undefined) return;
  const page = tab.url ? new URL(tab.url) : null;
  if (page?.protocol !== 'https:' || page.hostname !== 'www.youtube.com') {
    throw new Error('Abre una pestaña de YouTube para activar los subtítulos');
  }

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

  await ensureOffscreen();

  capture = { tabId: tab.id, videoId: info?.videoId ?? '' };
  await chrome.storage.session.set({ capture });
  await chrome.action.setBadgeText({ text: '...', tabId: tab.id });
  await chrome.action.setBadgeBackgroundColor({ color: '#24427C', tabId: tab.id });
  await chrome.action.setTitle({ title: t('YouJP: conectando'), tabId: tab.id });

  // El identificador caduca pronto: no preparar el overlay ni leer ajustes
  // después de obtenerlo, para que el offscreen pueda consumirlo de inmediato.
  const streamId = await getMediaStreamId(tab.id);

  await chrome.runtime.sendMessage({
    type: 'capture.start',
    streamId,
    tabId: tab.id,
    videoId: info?.videoId ?? '',
    url: tab.url ?? '',
    isLive: info?.isLive ?? false,
    mediaTimeMs: info?.mediaTimeMs ?? 0,
    paused: info.paused,
    rate: info.rate,
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
      .setTitle({ title: t('Activar subtítulos japoneses'), tabId: previous.tabId })
      .catch(() => {});
    await chrome.tabs
      .sendMessage(previous.tabId, { type: 'status', status: 'idle' } satisfies ExtensionMessage)
      .catch(() => {});
  }
  await chrome.offscreen.closeDocument().catch(() => {});
}

const screenStarts = new Map<number, Promise<void>>();
const screenRequests = new Map<string, { id: number; controller: AbortController }>();
function cancelTabScreenRequests(tabId: number): void {
  for (const [key, pending] of screenRequests) {
    if (!key.startsWith(`${tabId}:`)) continue;
    pending.controller.abort();
    screenRequests.delete(key);
  }
}

async function startScreenCapture(tab: chrome.tabs.Tab): Promise<void> {
  if (tab.id === undefined) return;
  const tabId = tab.id;
  if (!supportsScreenCapture(tab.url)) {
    throw new Error('El recorte requiere una página HTTP o HTTPS. El navegador bloquea sus páginas internas.');
  }
  if (screenStarts.has(tabId)) return screenStarts.get(tabId);
  const start = (async () => {
    const probe = () => chrome.tabs.sendMessage(tabId, { type: 'screen.probe' }, { frameId: 0 })
      .catch(() => null);
    if ((await probe())?.ready !== true) {
      await chrome.scripting.executeScript({ target: { tabId }, files: ['content-scripts/screen.js'] });
      if ((await probe())?.ready !== true) throw new Error('No se pudo iniciar el selector. Recarga la página.');
    }
    await chrome.tabs.sendMessage(tabId, { type: 'screen.select' }, { frameId: 0 });
  })();
  screenStarts.set(tabId, start);
  try { await start; } finally { screenStarts.delete(tabId); }
}

async function reportScreenError(tabId: number | undefined, error: unknown): Promise<void> {
  console.warn('[youjp] no se pudo iniciar la selección', error);
  if (tabId === undefined) return;
  const detail = error instanceof Error ? error.message : String(error);
  await chrome.action.setTitle({ tabId, title: `YouJP: ${t(detail)}` }).catch(() => {});
  await chrome.action.setBadgeText({ tabId, text: '!' }).catch(() => {});
}

export default defineBackground(() => {
  void loadSettings().then((settings) => {
    if (!languageChanged) uiLanguage = settings.settingsLanguage;
  });
  chrome.commands.onCommand.addListener((command, selectedTab) => {
    if (command !== 'translate-selection') return;
    void (async () => {
      const tab = selectedTab ?? (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
      if (!tab) return;
      await startScreenCapture(tab).catch((error) => reportScreenError(tab.id, error));
    })().catch((error) => console.warn('[youjp] no se pudo iniciar la selección', error));
  });

  chrome.runtime.onMessage.addListener((message: unknown, sender, respond) => {
    const tabId = sender.tab?.id;
    if (!message || typeof message !== 'object' || !('type' in message) ||
        !['screen.capture', 'screen.retry', 'screen.cancel'].includes(String(message.type)) || tabId === undefined ||
        sender.id !== chrome.runtime.id || sender.frameId !== 0) return;
    const key = `${tabId}:${sender.documentId ?? 'main'}`;
    const requestId = 'requestId' in message && typeof message.requestId === 'number' ? message.requestId : 0;
    if (message.type === 'screen.cancel') {
      const pending = screenRequests.get(key);
      if (pending?.id === requestId) pending.controller.abort();
      respond({ ok: true });
      return;
    }
    screenRequests.get(key)?.controller.abort();
    const controller = new AbortController();
    screenRequests.set(key, { id: requestId, controller });
    void (async () => {
      if (message.type === 'screen.capture' && (!('selection' in message) || !validSelection(message.selection))) {
        throw new Error('Selección no válida');
      }
      const tab = await chrome.tabs.get(tabId);
      if (sender.url !== tab.url) throw new Error('La página cambió. Vuelve a seleccionar el texto.');
      const { serverUrl = DEFAULT_SERVER_URL } = await chrome.storage.local.get('serverUrl');
      const settings = await loadSettings();
      if (message.type === 'screen.retry') {
        if (!('japanese' in message) || typeof message.japanese !== 'string' ||
            !message.japanese || message.japanese.length > 8000) throw new Error('Texto no válido');
        return retryScreenTranslation(message.japanese, serverUrl, settings.targetLanguage, controller.signal);
      }
      if (!('selection' in message) || !validSelection(message.selection)) throw new Error('Selección no válida');
      return captureAndTranslate(tab, message.selection, serverUrl, async () => {
        if (controller.signal.aborted) throw new Error('Captura cancelada');
        await chrome.tabs.sendMessage(tabId, { type: 'screen.capture.progress', requestId },
          sender.documentId ? { documentId: sender.documentId } : { frameId: 0 }).catch(() => {});
      }, settings.targetLanguage, controller.signal);
    })().then((result) => respond({ ok: true, result }))
      .catch((error) => respond({ ok: false, error: error instanceof Error ? error.message : String(error) }))
      .finally(() => { if (screenRequests.get(key)?.controller === controller) screenRequests.delete(key); });
    return true;
  });

  // Vídeo completo: el content script no puede hablar con el backend, así que
  // las peticiones pasan por aquí. Son cortas, no deja nada abierto.
  chrome.runtime.onMessage.addListener((message: unknown, sender, respond) => {
    if (!isVideoRequest(message) || sender.id !== chrome.runtime.id ||
        sender.tab === undefined || sender.frameId !== 0) return;
    void (async () => {
      const { serverUrl = DEFAULT_SERVER_URL } = await chrome.storage.local.get('serverUrl');
      return callVideoApi(serverUrl, message);
    })().then((data) => respond({ ok: true, data }))
      .catch((error) => respond({ ok: false, error: error instanceof Error ? error.message : String(error) }));
    return true;
  });

  // El documento offscreen solo tiene chrome.runtime: el almacenamiento y
  // sus eventos se atienden aquí, también al despertar el service worker.
  onSettingsChanged((settings) => {
    languageChanged = true;
    uiLanguage = settings.settingsLanguage;
    chrome.runtime.sendMessage({ type: 'settings.changed', settings } satisfies ExtensionMessage)
      .catch(() => {});
  });

  chrome.action.onClicked.addListener((tab) => {
    if (!tab.url?.startsWith('https://www.youtube.com/')) {
      return startScreenCapture(tab).catch((error) => reportScreenError(tab.id, error));
    }
    return queueCapture(async () => {
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
      await stopCapture();
      if (tab.id) {
        // El overlay puede no existir justo cuando falla, así que el aviso va
        // también al icono: es el único sitio que siempre se ve.
        await chrome.action.setBadgeText({ text: '!', tabId: tab.id }).catch(() => {});
        await chrome.action
          .setBadgeBackgroundColor({ color: '#B8422B', tabId: tab.id })
          .catch(() => {});
        await chrome.action.setTitle({ title: `YouJP: ${t(detail)}`, tabId: tab.id }).catch(() => {});
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
      const activeCapture = capture;
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
        if (message.type === 'status' && capture === activeCapture) {
          await chrome.action.setBadgeText({ tabId,
            text: message.status === 'running' ? 'ON' : message.status === 'idle' ? '' : message.status === 'error' ? '!' : '...' });
          await chrome.action.setTitle({ tabId,
            title: `YouJP: ${t(message.detail || message.status)}` });
          if (message.status === 'error') {
            await queueCapture(async () => {
              if (capture !== activeCapture) return;
              capture = null;
              await chrome.storage.session.remove('capture');
              await chrome.offscreen.closeDocument().catch(() => {});
            });
          }
        }
      }
    }).catch(console.warn);
  });

  // Si la pestaña capturada se cierra o navega fuera, la captura ya no tiene
  // sentido: el streamId queda huérfano y el audio deja de llegar.
  chrome.tabs.onRemoved.addListener((tabId) => {
    cancelTabScreenRequests(tabId);
    void queueCapture(async () => {
      await restored;
      if (capture?.tabId === tabId) await stopCapture();
    }).catch(console.warn);
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (changeInfo.status !== 'loading') return;
    cancelTabScreenRequests(tabId);
    void queueCapture(async () => {
      await restored;
      if (capture?.tabId === tabId) await stopCapture();
    }).catch(console.warn);
  });
});
