/**
 * Overlay de subtítulos sobre el reproductor.
 *
 * Dos líneas y nada más, que es lo que pide el MVP: el texto confirmado en
 * blanco y la cola tentativa en gris. Esa distinción no es decorativa — el
 * prefijo confirmado por LocalAgreement ya no cambiará nunca, y la cola se
 * reescribe cada 0,8 s. Pintarlos igual haría que el subtítulo pareciera
 * bailar sin motivo.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { AsrFinal, AsrPartial, MetricsTick, Token } from '../protocol';
import type { CaptureStatus, ExtensionMessage } from '../messages';
import { WordCard } from './WordCard';

const MAX_HISTORY = 3;

/**
 * Una frase cerrada.
 *
 * El japonés llega primero; la traducción y los tokens vienen después y por
 * separado, cada uno cuando está listo. Por eso `es` y `tokens` empiezan vacíos
 * y se rellenan al llegar el mensaje con el mismo `segment_id`.
 */
interface Line {
  id: number;
  ja: string;
  es: string;
  tokens: Token[];
}

const STATUS_LABEL: Record<CaptureStatus, string> = {
  idle: 'inactivo',
  starting: 'iniciando…',
  connecting: 'conectando con el backend…',
  running: 'en marcha',
  reconnecting: 'reconectando…',
  error: 'error',
};

export function Overlay() {
  const [status, setStatus] = useState<CaptureStatus>('idle');
  const [detail, setDetail] = useState('');
  const [model, setModel] = useState('');
  const [partial, setPartial] = useState<AsrPartial | null>(null);
  const [history, setHistory] = useState<Line[]>([]);
  const [metrics, setMetrics] = useState<MetricsTick | null>(null);
  const [showMetrics, setShowMetrics] = useState(false);
  const [rateWarning, setRateWarning] = useState<number | null>(null);
  const [selected, setSelected] = useState<Token | null>(null);
  const lastFinal = useRef(0);

  const closeCard = useCallback(() => setSelected(null), []);

  useEffect(() => {
    const listener = (message: ExtensionMessage) => {
      switch (message.type) {
        case 'status':
          setStatus(message.status);
          setDetail(message.detail ?? '');
          if (message.model) setModel(message.model);
          if (message.status === 'idle') {
            setPartial(null);
            setHistory([]);
            setSelected(null);
          }
          break;
        case 'subtitle.partial':
          setPartial(message.payload);
          break;
        case 'subtitle.final': {
          const final = message.payload as AsrFinal;
          if (final.segment_id === lastFinal.current) break;
          lastFinal.current = final.segment_id;
          setHistory((prev) =>
            [...prev, { id: final.segment_id, ja: final.text, es: '', tokens: [] }].slice(
              -MAX_HISTORY,
            ),
          );
          setPartial(null);
          break;
        }
        case 'subtitle.translation': {
          const { segment_id, text_es } = message.payload;
          // La traducción puede llegar cuando la frase ya ha salido del
          // historial: en ese caso no hay nada que actualizar y se descarta.
          setHistory((prev) =>
            prev.map((line) => (line.id === segment_id ? { ...line, es: text_es } : line)),
          );
          break;
        }
        case 'subtitle.tokens': {
          const { segment_id, tokens } = message.payload;
          setHistory((prev) =>
            prev.map((line) => (line.id === segment_id ? { ...line, tokens } : line)),
          );
          break;
        }
        case 'metrics':
          setMetrics(message.payload);
          break;
        case 'backend.error':
          setStatus('error');
          setDetail(message.payload.message);
          break;
      }
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey && event.code === 'KeyM') {
        event.preventDefault();
        setShowMetrics((value) => !value);
      }
      if (event.key === 'Escape') setSelected(null);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, []);

  useEffect(() => {
    const listener = (event: Event) => {
      const rate = (event as CustomEvent<number>).detail;
      setRateWarning(Math.abs(rate - 1) > 0.01 ? rate : null);
    };
    window.addEventListener('youjp:rate', listener);
    return () => window.removeEventListener('youjp:rate', listener);
  }, []);

  if (status === 'idle' && history.length === 0) return null;

  const committed = partial?.committed ?? '';
  const tentative = partial?.tentative ?? '';

  return (
    <div className="youjp-root">
      {status !== 'running' && (
        <div className={`youjp-status youjp-status--${status}`}>
          <span className="youjp-dot" />
          {STATUS_LABEL[status]}
          {detail && <span className="youjp-detail">{detail}</span>}
        </div>
      )}

      {rateWarning !== null && (
        <div className="youjp-status youjp-status--error">
          Velocidad {rateWarning}× — la transcripción está pausada. El audio acelerado
          se transcribe mal y descuadra los tiempos.
        </div>
      )}

      {selected && <WordCard token={selected} onClose={closeCard} />}

      <div className="youjp-subs">
        {history.map((line, index) => {
          const actual = index === history.length - 1;
          return (
            <div key={line.id} className={actual ? 'youjp-block' : 'youjp-block youjp-block--past'}>
              <p className="youjp-line">
                {line.tokens.length > 0
                  ? line.tokens.map((token) =>
                      token.clickable ? (
                        <button
                          key={token.i}
                          className={
                            selected?.i === token.i && selected.surface === token.surface
                              ? 'youjp-token youjp-token--active'
                              : 'youjp-token'
                          }
                          onClick={() => setSelected(token)}
                          title={token.kana || undefined}
                        >
                          {token.surface}
                        </button>
                      ) : (
                        // Partículas, auxiliares y puntuación: se pintan, pero
                        // no se pulsan. Una tarjeta para は sería ruido.
                        <span key={token.i} className="youjp-token youjp-token--plain">
                          {token.surface}
                        </span>
                      ),
                    )
                  : line.ja}
              </p>
              {line.es && <p className="youjp-es">{line.es}</p>}
            </div>
          );
        })}
        {(committed || tentative) && (
          <div className="youjp-block">
            <p className="youjp-line">
              <span className="youjp-committed">{committed}</span>
              <span className="youjp-tentative">{tentative}</span>
            </p>
          </div>
        )}
      </div>

      {showMetrics && metrics && (
        <div className="youjp-metrics">
          <span title="latencia extremo a extremo">
            e2e <b>{metrics.end_to_end_ms_p50.toFixed(0)}</b>/
            {metrics.end_to_end_ms_p95.toFixed(0)} ms
          </span>
          <span title="inferencia de Whisper">
            asr <b>{metrics.whisper_processing_ms_p50.toFixed(0)}</b> ms
          </span>
          <span title="audio pendiente en la cola del backend">
            buf <b>{metrics.audio_buffer_ms.toFixed(0)}</b> ms
          </span>
          <span
            title="tramas de audio descartadas — debe quedarse en cero"
            className={metrics.dropped_audio_chunks > 0 ? 'youjp-bad' : undefined}
          >
            drop <b>{metrics.dropped_audio_chunks}</b>
          </span>
          <span title="parciales / finales">
            {metrics.partial_transcripts}/{metrics.final_transcripts}
          </span>
          <span title="pasadas de Whisper / saltadas por el VAD">
            pas {metrics.passes}/<b>{metrics.skipped_silent}</b>
          </span>
          <span title="análisis morfológico y consulta de diccionario">
            nlp <b>{metrics.nlp_ms_p50.toFixed(1)}</b> ms
          </span>
          <span title="traducción: latencia p50 y frases traducidas">
            mt <b>{metrics.translation_latency_ms_p50.toFixed(0)}</b> ms ·{' '}
            {metrics.translations}
            {metrics.dropped_translations > 0 && (
              <span className="youjp-bad"> (−{metrics.dropped_translations})</span>
            )}
          </span>
          <span
            title="VRAM usada — por debajo de 500 MiB libres el sistema empieza a degradarse"
            className={
              metrics.gpu_total_mb - metrics.gpu_used_mb < 500 ? 'youjp-bad' : undefined
            }
          >
            gpu <b>{metrics.gpu_used_mb.toFixed(0)}</b>/{metrics.gpu_total_mb.toFixed(0)} MiB
          </span>
          {model && <span className="youjp-model">{model}</span>}
        </div>
      )}
    </div>
  );
}
