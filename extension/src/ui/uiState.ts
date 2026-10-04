/**
 * Estado que el overlay publica para los botones de la barra del reproductor.
 *
 * Los botones los monta `content.tsx` fuera del overlay (en los controles de
 * YouTube), así que no pueden leer el estado de React: lo reciben por evento.
 */

export const UI_STATE_EVENT = 'youjp:ui-state';

export type VideoPhase = 'none' | 'working' | 'ready' | 'error';

export interface VideoUiState {
  phase: VideoPhase;
  /** 0..1 */
  progress: number;
  /** Con el vídeo ya traducido: si sus subtítulos están encendidos. */
  enabled: boolean;
  message: string;
}

export interface UiState {
  settingsOpen: boolean;
  video: VideoUiState;
}

export const INITIAL_UI_STATE: UiState = {
  settingsOpen: false,
  video: { phase: 'none', progress: 0, enabled: true, message: '' },
};
