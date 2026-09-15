/**
 * Renderizado de una línea de subtítulo con furigana opcional.
 *
 * La furigana es la función de legibilidad más importante en japonés, pero
 * ponerla en todo es contraproducente pasado cierto nivel: se acaba leyendo solo
 * el kana y los kanji dejan de aprenderse. Por eso el modo por defecto es
 * `auto`, que solo la pone donde probablemente hace falta — palabras que JMdict
 * no marca como comunes.
 */

import type { Token } from '../protocol';
import type { FuriganaMode } from '../settings';

const KANJI = /[一-龯㐀-䶿]/;

function hasKanji(text: string): boolean {
  return KANJI.test(text);
}

/**
 * Si esta palabra lleva furigana según el modo elegido.
 *
 * Sin kanji no hay nada que anotar, y si la lectura coincide con la superficie
 * tampoco: poner ruby sobre きっかけ solo añade ruido.
 */
function needsFurigana(token: Token, mode: FuriganaMode): boolean {
  if (mode === 'off') return false;
  if (!token.kana || !hasKanji(token.surface) || token.kana === token.surface) return false;
  if (mode === 'all') return true;
  // auto: solo lo que probablemente no se reconoce de vista.
  return !token.entry?.common;
}

interface Props {
  text: string;
  tokens: Token[];
  furigana: FuriganaMode;
  selectedIndex: number | null;
  onSelect: (token: Token) => void;
}

export function Subtitle({ text, tokens, furigana, selectedIndex, onSelect }: Props) {
  // Mientras no llega el análisis se pinta el texto plano. Es lo que hace que
  // el japonés aparezca sin esperar a nadie.
  if (tokens.length === 0) return <>{text}</>;

  return (
    <>
      {tokens.map((token) => {
        const cuerpo = needsFurigana(token, furigana) ? (
          <ruby>
            {token.surface}
            <rt>{token.kana}</rt>
          </ruby>
        ) : (
          token.surface
        );

        if (!token.clickable) {
          // Partículas, auxiliares y puntuación: se pintan, no se pulsan.
          return (
            <span key={token.i} className="youjp-token youjp-token--plain">
              {cuerpo}
            </span>
          );
        }

        return (
          <button
            key={token.i}
            className={
              selectedIndex === token.i ? 'youjp-token youjp-token--active' : 'youjp-token'
            }
            onClick={() => onSelect(token)}
            title={token.kana || undefined}
          >
            {cuerpo}
          </button>
        );
      })}
    </>
  );
}
