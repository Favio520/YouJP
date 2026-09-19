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
 *
 * El panel se mueve y se redimensiona por su cuenta, independiente de los
 * subtítulos: mientras se consulta el historial hay que poder seguir viendo la
 * frase actual, así que tienen que poder ocupar sitios distintos.
 */

import { useEffect, useRef } from 'react';
import type { Line } from './types';
import { useDrag, type Position } from './useDrag';

interface Props {
  lines: Line[];
  position: Position | null;
  onMove: (position: Position) => void;
  onResetPosition: () => void;
  onSeek: (mediaMs: number) => void;
  onClose: () => void;
  showTranslation: boolean;
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

export function TranscriptPanel({
  lines,
  position,
  onMove,
  onResetPosition,
  onSeek,
  onClose,
  showTranslation,
}: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const pegadoAbajo = useRef(true);
  const { dragging, preview, empezar } = useDrag(onMove);

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

  const actual = preview ?? position;
  const estilo = actual
    ? ({ left: `${actual.x}%`, top: `${actual.y}%`, bottom: 'auto', right: 'auto' } as const)
    : undefined;

  return (
    <div
      className={
        actual
          ? `youjp-transcript youjp-transcript--free${dragging ? ' youjp-transcript--dragging' : ''}`
          : 'youjp-transcript'
      }
      style={estilo}
      role="dialog"
      aria-label="Historial de la sesión"
    >
      {/* La cabecera entera es el asa: es la zona que no tiene nada pulsable
          dentro, así que arrastrar desde ahí no compite con nada. */}
      <div className="youjp-transcript-head" onMouseDown={empezar}>
        <span className="youjp-transcript-title">Historial · {lines.length} frases</span>
        {actual && (
          <button
            className="youjp-transcript-action"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={onResetPosition}
            title="Devolver el panel a su sitio"
          >
            ⌖
          </button>
        )}
        <button
          className="youjp-transcript-action"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={onClose}
          aria-label="Cerrar"
        >
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
              {showTranslation && line.translation && (
                <span className="youjp-transcript-es" lang={line.target ?? undefined}>
                  <small>{line.target?.toUpperCase()} · </small>{line.translation}
                </span>
              )}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
