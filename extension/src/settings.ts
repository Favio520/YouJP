/**
 * Ajustes de presentación del overlay.
 *
 * Se guardan en `chrome.storage.local` y se aplican en vivo mientras se ve el
 * vídeo: ajustar el tamaño del texto a ciegas desde una pantalla de opciones y
 * volver a mirar no funciona — hay que ver el efecto sobre el fotograma real.
 *
 * Todo lo que cambia el aspecto sale de aquí y viaja como variables CSS, así que
 * la hoja de estilos no necesita saber nada de React.
 */

import type { TargetLanguage } from './protocol';

export type FuriganaMode = 'off' | 'auto' | 'all';
export type BackdropMode = 'none' | 'soft' | 'solid';
export type LanguageMode = 'both' | 'ja' | 'translation';

export interface OverlaySettings {
  /** Tamaño del japonés en píxeles a 1080p; escala con el ancho del vídeo. */
  jaSize: number;
  translationSize: number;
  targetLanguage: TargetLanguage;
  /** Distancia desde el borde inferior del reproductor, en píxeles. */
  bottom: number;
  /** Ancho máximo del bloque de subtítulos, en porcentaje del vídeo. */
  width: number;
  furigana: FuriganaMode;
  backdrop: BackdropMode;
  languages: LanguageMode;
  /** Frases anteriores visibles, 0 a 3. */
  history: number;
  /** Mostrar la cola tentativa en gris. Quitarla da un subtítulo más estable
   *  a cambio de que aparezca más tarde. */
  showTentative: boolean;

  /**
   * Posición libre, en porcentaje del reproductor.
   *
   * `null` significa el sitio de siempre: abajo y centrado, a `bottom` píxeles
   * del borde. En cuanto se arrastra el overlay pasa a coordenadas libres, y
   * entonces `bottom` deja de aplicarse. En porcentaje y no en píxeles para que
   * sobreviva al cambio de tamaño y a la pantalla completa.
   */
  position: { x: number; y: number } | null;

  /** Posición del panel de historial, con el mismo criterio que `position`. */
  transcriptPosition: { x: number; y: number } | null;
}

export const DEFAULT_SETTINGS: OverlaySettings = {
  jaSize: 28,
  translationSize: 21,
  targetLanguage: 'es',
  bottom: 72,
  width: 86,
  // `auto` pone furigana solo donde probablemente hace falta. Ponerla en todo
  // es contraproducente pasado cierto nivel: se acaba leyendo solo el kana y
  // los kanji dejan de aprenderse.
  furigana: 'auto',
  backdrop: 'soft',
  languages: 'both',
  history: 1,
  showTentative: true,
  position: null,
  transcriptPosition: null,
};

const KEY = 'overlaySettings';

/** Migrate the Spanish-only settings without losing saved display preferences. */
export function normalizeSettings(value: unknown): OverlaySettings {
  const stored = value && typeof value === 'object'
    ? value as Record<string, unknown> : {};
  const { esSize, ...rest } = stored;
  const current = { ...DEFAULT_SETTINGS, ...rest };
  return {
    ...current,
    translationSize: typeof stored.translationSize === 'number'
      ? stored.translationSize : typeof esSize === 'number' ? esSize : DEFAULT_SETTINGS.translationSize,
    targetLanguage: stored.targetLanguage === 'en' ? 'en' : 'es',
    languages: stored.languages === 'es' || stored.languages === 'translation'
      ? 'translation' : stored.languages === 'ja' ? 'ja' : 'both',
  } as OverlaySettings;
}

export async function loadSettings(): Promise<OverlaySettings> {
  try {
    const stored = await chrome.storage.local.get(KEY);
    return normalizeSettings(stored[KEY]);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export async function saveSettings(settings: OverlaySettings): Promise<void> {
  try {
    await chrome.storage.local.set({ [KEY]: settings });
  } catch {
    // Sin almacenamiento los ajustes duran lo que la sesión. No es motivo para
    // romper el overlay.
  }
}

/** Escucha cambios hechos desde otra pestaña. */
export function onSettingsChanged(fn: (settings: OverlaySettings) => void): () => void {
  const listener = (
    changes: Record<string, chrome.storage.StorageChange>,
    area: string,
  ) => {
    if (area === 'local' && changes[KEY]?.newValue) {
      fn(normalizeSettings(changes[KEY].newValue));
    }
  };
  chrome.storage.onChanged.addListener(listener);
  return () => chrome.storage.onChanged.removeListener(listener);
}

/** Traduce los ajustes a las variables CSS que consume la hoja de estilos. */
export function toCssVars(s: OverlaySettings): Record<string, string> {
  const vars: Record<string, string> = {
    '--youjp-ja-size': `${s.jaSize}px`,
    '--youjp-es-size': `${s.translationSize}px`,
    '--youjp-bottom': `${s.bottom}px`,
    '--youjp-width': `${s.width}%`,
  };
  if (s.position) {
    vars['--youjp-x'] = `${s.position.x}%`;
    vars['--youjp-y'] = `${s.position.y}%`;
  }
  return vars;
}
