/**
 * Observación del reproductor de YouTube.
 *
 * El backend necesita dos cosas de aquí: la posición dentro del vídeo, para
 * anclar los subtítulos, y un aviso inmediato cuando esa posición deja de ser
 * continua. Sin lo segundo, tras un salto el pipeline seguiría transcribiendo
 * audio viejo contra una hipótesis que ya no vale.
 *
 * Los selectores están anclados a clases que YouTube cambia de vez en cuando, y
 * por eso hay varios de respaldo y un `MutationObserver` que vuelve a buscar.
 */

const PLAYER_SELECTORS = ['#movie_player', '.html5-video-player'];
const VIDEO_SELECTORS = ['video.html5-main-video', '#movie_player video', 'video'];

export interface PlayerSnapshot {
  mediaTimeMs: number;
  paused: boolean;
  rate: number;
  videoId: string;
  isLive: boolean;
}

export function findPlayerRoot(): HTMLElement | null {
  for (const selector of PLAYER_SELECTORS) {
    const element = document.querySelector<HTMLElement>(selector);
    if (element) return element;
  }
  return null;
}

export function findVideo(): HTMLVideoElement | null {
  for (const selector of VIDEO_SELECTORS) {
    const element = document.querySelector<HTMLVideoElement>(selector);
    if (element) return element;
  }
  return null;
}

export function currentVideoId(): string {
  return new URLSearchParams(location.search).get('v') ?? '';
}

/**
 * Un directo no tiene línea temporal fija: `duration` es infinita y el usuario
 * puede estar en el borde o desplazado dentro del DVR.
 */
export function isLive(video: HTMLVideoElement | null): boolean {
  if (video && !Number.isFinite(video.duration)) return true;
  return Boolean(document.querySelector('.ytp-live-badge, .ytp-live'));
}

export function snapshot(): PlayerSnapshot {
  const video = findVideo();
  return {
    mediaTimeMs: video ? video.currentTime * 1000 : 0,
    paused: video ? video.paused : true,
    rate: video ? video.playbackRate : 1,
    videoId: currentVideoId(),
    isLive: isLive(video),
  };
}

export interface PlayerWatchHandlers {
  onTick: (snap: PlayerSnapshot) => void;
  onFlush: (reason: 'seek' | 'pause' | 'rate', snap: PlayerSnapshot) => void;
  /** Velocidad distinta de 1x: el audio capturado va acelerado y Whisper lo
   *  transcribe mal, además de descuadrar todos los tiempos. */
  onRateWarning: (rate: number) => void;
}

const TICK_MS = 250;

export function watchPlayer(handlers: PlayerWatchHandlers): () => void {
  let video: HTMLVideoElement | null = null;
  let detach: (() => void) | null = null;

  const attach = (element: HTMLVideoElement) => {
    detach?.();
    video = element;

    const onSeeked = () => handlers.onFlush('seek', snapshot());
    const onPause = () => handlers.onFlush('pause', snapshot());
    const onRate = () => {
      const snap = snapshot();
      handlers.onFlush('rate', snap);
      if (Math.abs(snap.rate - 1) > 0.01) handlers.onRateWarning(snap.rate);
    };

    element.addEventListener('seeked', onSeeked);
    element.addEventListener('pause', onPause);
    element.addEventListener('ratechange', onRate);

    detach = () => {
      element.removeEventListener('seeked', onSeeked);
      element.removeEventListener('pause', onPause);
      element.removeEventListener('ratechange', onRate);
    };
  };

  const found = findVideo();
  if (found) attach(found);

  // YouTube es una SPA: al navegar entre vídeos reemplaza el elemento sin
  // recargar la página, y los listeners se quedan colgados de un nodo huérfano.
  const observer = new MutationObserver(() => {
    const element = findVideo();
    if (element && element !== video) attach(element);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  const timer = window.setInterval(() => {
    if (video && !video.paused) handlers.onTick(snapshot());
  }, TICK_MS);

  return () => {
    window.clearInterval(timer);
    observer.disconnect();
    detach?.();
  };
}
