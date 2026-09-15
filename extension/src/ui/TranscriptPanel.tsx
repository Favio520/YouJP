/**
 * Historial completo de la sesión.
 *
 * El overlay solo enseña la frase actual y unas pocas anteriores, porque lo
 * contrario taparía el vídeo. Pero al estudiar hace falta poder volver: releer
 * una frase que pasó rápido, comprobar una traducción, o saltar al momento en
 * que se dijo.
 *
 * Por eso cada línea es pulsable y lleva el vídeo a su marca temporal. Es la
 * diferencia entre un subtítulo y algo con lo que se puede estudiar.
 */

import { useEffect, useRef } from 'react';
import type { Line } from './types';

interface Props {
  lines: Line[];
  onSeek: (mediaMs: number) => void;
  onClose: () => void;
  showEs: boolean;
}

function marca(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(h > 0 ? 2 : 1, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function TranscriptPanel({ lines, onSeek, onClose, showEs }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const pegadoAbajo = useRef(true);

  // Autoscroll solo si el usuario ya estaba al final. Si ha subido a releer
  // algo, arrastrarle hacia abajo en cada frase nueva haría el panel inservible
  // justo cuando más se está usando.
  useEffect(() => {
    const el = scroller.current;
    if (el && pegadoAbajo.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    pegadoAbajo.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
  };

  return (
    <div className="youjp-transcript" role="dialog" aria-label="Historial de la sesión">
      <div className="youjp-settings-head">
        <span>Historial · {lines.length} frases</span>
        <button className="youjp-card-close" onClick={onClose} aria-label="Cerrar">
          ×
        </button>
      </div>

      <div className="youjp-transcript-body" ref={scroller} onScroll={onScroll}>
        {lines.length === 0 && (
          <p className="youjp-transcript-empty">
            Todavía no hay frases. Aparecerán aquí según se transcriban.
          </p>
        )}
        {lines.map((line) => (
          <button
            key={line.id}
            className="youjp-transcript-row"
            onClick={() => onSeek(line.mediaStartMs)}
            title="Ir a este momento del vídeo"
          >
            <span className="youjp-transcript-time">{marca(line.mediaStartMs)}</span>
            <span className="youjp-transcript-text">
              <span className="youjp-transcript-ja">{line.ja}</span>
              {showEs && line.es && <span className="youjp-transcript-es">{line.es}</span>}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
