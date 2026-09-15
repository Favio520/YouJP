/**
 * Tarjeta de palabra.
 *
 * Todo lo que se muestra aquí es determinista: viene de Sudachi y de JMdict, no
 * de un modelo. Esa distinción no es cosmética — cuando en la fase 5 se añadan
 * explicaciones generadas, tendrán que ir claramente separadas, porque quien
 * está aprendiendo no puede detectar una lectura inventada.
 */

import type { Token } from '../protocol';

interface Props {
  token: Token;
  onClose: () => void;
}

/** Marcadores de JMdict que cambian cómo se usa la palabra. */
const POS_TAGS: Record<string, string> = {
  n: 'sustantivo',
  vs: 'admite する',
  vi: 'intransitivo',
  vt: 'transitivo',
  'adj-i': 'adjetivo -i',
  'adj-na': 'adjetivo -na',
  adv: 'adverbio',
  exp: 'expresión',
  int: 'interjección',
  pn: 'pronombre',
  conj: 'conjunción',
  prt: 'partícula',
};

export function WordCard({ token, onClose }: Props) {
  const entry = token.entry;
  if (!entry) return null;

  const conjugado = token.chain.length > 0 && token.surface !== token.lemma;

  return (
    <div className="youjp-card" role="dialog" aria-label={`Definición de ${entry.headword}`}>
      <button className="youjp-card-close" onClick={onClose} aria-label="Cerrar">
        ×
      </button>

      <div className="youjp-card-head">
        <div className="youjp-card-word">{entry.headword}</div>
        {token.kana && <div className="youjp-card-kana">{token.kana}</div>}
        {token.romaji && <div className="youjp-card-romaji">{token.romaji}</div>}
      </div>

      <div className="youjp-card-body">
        <div className="youjp-card-tags">
          {token.pos_label && <span className="youjp-tag">{token.pos_label}</span>}
          {entry.common && <span className="youjp-tag youjp-tag--common">común</span>}
          {entry.freq_rank !== null && (
            <span className="youjp-tag" title="Grupo de frecuencia de JMdict: 1 es el más común">
              frec. {entry.freq_rank}
            </span>
          )}
        </div>

        {conjugado && (
          <div className="youjp-card-section">
            <div className="youjp-card-label">Conjugación</div>
            <div className="youjp-chain">
              <span className="youjp-chain-lemma">{token.lemma}</span>
              <span className="youjp-chain-arrow">→</span>
              <span className="youjp-chain-surface">{token.surface}</span>
            </div>
            <div className="youjp-chain-steps">
              {token.chain.map((paso) => (
                <span key={paso} className="youjp-step">
                  {paso}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="youjp-card-section">
          <div className="youjp-card-label">
            Significado <span className="youjp-source">JMdict</span>
          </div>
          <ol className="youjp-senses">
            {entry.senses.map((sense, i) => {
              const tags = sense.pos
                .map((p) => POS_TAGS[p])
                .filter(Boolean)
                .slice(0, 3);
              // El español de JMdict cubre una parte de las entradas. Cuando
              // falta se muestra el inglés, marcado: es mejor que un hueco, pero
              // el estudiante debe saber que no es una acepción revisada.
              const enEspanol = sense.glosses_es.length > 0;
              const glosas = enEspanol ? sense.glosses_es : sense.glosses_en;
              if (glosas.length === 0) return null;
              return (
                <li key={i}>
                  {tags.length > 0 && <span className="youjp-sense-tags">{tags.join(' · ')}</span>}
                  <span className={enEspanol ? undefined : 'youjp-gloss-en'}>
                    {glosas.slice(0, 4).join('; ')}
                  </span>
                  {!enEspanol && <span className="youjp-lang-badge">en inglés</span>}
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </div>
  );
}
