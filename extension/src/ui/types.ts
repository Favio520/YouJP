import type { TargetLanguage, Token } from '../protocol';

/**
 * Una frase cerrada de la sesión.
 *
 * El japonés llega primero; la traducción y los tokens vienen después y por
 * separado, cada uno cuando está listo. Por eso `translation` y `tokens` empiezan vacíos
 * y se rellenan al llegar el mensaje con el mismo `segment_id`.
 */
export interface Line {
  id: number;
  ja: string;
  translation: string;
  target: TargetLanguage | null;
  tokens: Token[];
  /** Posición dentro del vídeo, para poder volver a ella desde el historial. */
  mediaStartMs: number;
}

/** Palabra abierta en la tarjeta. La frase importa: `token.i` solo es único
 *  dentro de su frase, y sin `lineId` se resaltaría la misma posición en todas. */
export interface Selection {
  lineId: number;
  token: Token;
  /** Dónde se pulsó, para abrir la tarjeta junto a esa palabra. */
  from: 'subtitles' | 'transcript';
}
