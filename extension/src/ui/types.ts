import type { Token } from '../protocol';

/**
 * Una frase cerrada de la sesión.
 *
 * El japonés llega primero; la traducción y los tokens vienen después y por
 * separado, cada uno cuando está listo. Por eso `es` y `tokens` empiezan vacíos
 * y se rellenan al llegar el mensaje con el mismo `segment_id`.
 */
export interface Line {
  id: number;
  ja: string;
  es: string;
  tokens: Token[];
  /** Posición dentro del vídeo, para poder volver a ella desde el historial. */
  mediaStartMs: number;
}
