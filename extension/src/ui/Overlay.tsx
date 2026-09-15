/**
 * Overlay de subtítulos sobre el reproductor.
 *
 * El texto confirmado va en blanco y la cola tentativa en gris. Esa distinción
 * no es decorativa: el prefijo confirmado por LocalAgreement ya no cambiará
 * nunca, y la cola se reescribe cada 0,8 s. Pintarlos igual haría que el
 * subtítulo pareciera bailar sin motivo.
 *
 * Todo lo que afecta a la legibilidad —tamaño, altura, fondo, furigana— es
 * ajustable en vivo desde el panel de la rueda dentada. Ver `settings.ts`.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { AsrFinal, AsrPartial, MetricsTick, Token } from '../protocol';
import type { CaptureStatus, ExtensionMessage } from '../messages';
import {
  DEFAULT_SETTINGS,
  loadSettings,
  onSettingsChanged,
  saveSettings,
  toCssVars,
  type OverlaySettings,
} from '../settings';
import { findVideo } from '../player';
import { SettingsPanel } from './SettingsPanel';
import { Subtitle } from './Subtitle';
import { TranscriptPanel } from './TranscriptPanel';
import type { Line } from './types';
import { useDrag } from './useDrag';
import { WordCard } from './WordCard';

const MAX_LINES = 4; // la actual mas tres de historial en el overlay

/** Frases que se conservan para el historial completo. Una sesion larga de
 *  estudio son unos cientos; mas alla no se consulta y solo ocupa. */
const MAX_LOG = 300;

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
  const [settings, setSettings] = useState<OverlaySettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  const lastFinal = useRef(0);

  const closeCard = useCallback(() => setSelected(null), []);

  const patchSettings = useCallback((patch: Partial<OverlaySettings>) => {
    setSettings((previous) => {
      const next = { ...previous, ...patch };
      void saveSettings(next);
      return next;
    });
  }, []);

  useEffect(() => {
    void loadSettings().then(setSettings);
    return onSettingsChanged(setSettings);
  }, []);

  const { dragging, preview, empezar } = useDrag(
    useCallback((position) => patchSettings({ position }), [patchSettings]),
  );

  /** Lleva el vídeo a una frase del historial. */
  const seek = useCallback((mediaMs: number) => {
    const video = findVideo();
    if (!video) return;
    // Un pelín antes del inicio de la frase: caer justo en el límite corta la
    // primera sílaba, que es precisamente la que se quería volver a oír.
    video.currentTime = Math.max(0, mediaMs / 1000 - 0.4);
    if (video.paused) void video.play().catch(() => {});
  }, []);

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
            [
              ...prev,
              {
                id: final.segment_id,
                ja: final.text,
                es: '',
                tokens: [],
                mediaStartMs: final.media_start_ms,
              },
            ].slice(-MAX_LOG),
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
      if (event.altKey && event.code === 'KeyS') {
        event.preventDefault();
        setShowSettings((value) => !value);
      }
      if (event.altKey && event.code === 'KeyH') {
        event.preventDefault();
        setShowTranscript((value) => !value);
      }
      if (event.key === 'Escape') {
        setSelected(null);
        setShowSettings(false);
        setShowTranscript(false);
      }
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

  const visible = settings.history >= MAX_LINES ? history : history.slice(-(settings.history + 1));
  const committed = partial?.committed ?? '';
  const tentative = settings.showTentative ? (partial?.tentative ?? '') : '';
  const showJa = settings.languages !== 'es';
  const showEs = settings.languages !== 'ja';

  // Durante el arrastre manda la posición provisional, para que el overlay siga
  // al cursor sin escribir en el almacenamiento en cada píxel.
  const posicion = preview ?? settings.position;
  const libre = posicion !== null;
  const estilo = {
    ...toCssVars(settings),
    ...(posicion ? { '--youjp-x': `${posicion.x}%`, '--youjp-y': `${posicion.y}%` } : {}),
  } as React.CSSProperties;

  return (
    <>
      {/* El historial va fuera de `.youjp-root`, como hermano y no como hijo:
          los dos se posicionan respecto al reproductor y se mueven por separado.
          Anidado heredaría la transformación del overlay y arrastrar uno movería
          el otro. */}
      {showTranscript && (
        <TranscriptPanel
          lines={history}
          position={settings.transcriptPosition}
          onMove={(transcriptPosition) => patchSettings({ transcriptPosition })}
          onResetPosition={() => patchSettings({ transcriptPosition: null })}
          onSeek={seek}
          onClose={() => setShowTranscript(false)}
          showEs={showEs}
        />
      )}

      <div
        className={[
          'youjp-root',
          `youjp-bg--${settings.backdrop}`,
          libre ? 'youjp-root--free' : '',
          dragging ? 'youjp-root--dragging' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        style={estilo}
      >
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

      {showSettings && (
        <SettingsPanel
          settings={settings}
          onChange={patchSettings}
          onClose={() => setShowSettings(false)}
        />
      )}

      {selected && <WordCard token={selected} onClose={closeCard} />}

      <div className="youjp-subs">
        {visible.map((line, index) => {
          const actual = index === visible.length - 1;
          return (
            <div key={line.id} className={actual ? 'youjp-block' : 'youjp-block youjp-block--past'}>
              {showJa && (
                <p className="youjp-line">
                  <Subtitle
                    text={line.ja}
                    tokens={line.tokens}
                    furigana={settings.furigana}
                    selectedIndex={selected?.i ?? null}
                    onSelect={setSelected}
                  />
                </p>
              )}
              {showEs && line.es && <p className="youjp-es">{line.es}</p>}
            </div>
          );
        })}

        {showJa && (committed || tentative) && (
          <div className="youjp-block">
            <p className="youjp-line">
              <span className="youjp-committed">{committed}</span>
              <span className="youjp-tentative">{tentative}</span>
            </p>
          </div>
        )}
      </div>

      <div className="youjp-tools">
        {/* El asa está separada del subtítulo a propósito: el subtítulo está
            lleno de palabras pulsables y arrastrarlo por ahí abriría tarjetas
            al azar. */}
        <button
          className="youjp-tool youjp-grip"
          onMouseDown={empezar}
          title="Arrastrar para mover los subtítulos"
          aria-label="Mover los subtítulos"
        >
          ⠿
        </button>
        <button
          className="youjp-tool"
          onClick={() => setShowTranscript((value) => !value)}
          title={`Historial de la sesión · ${history.length} frases (Alt+H)`}
          aria-label="Historial de la sesión"
        >
          ☰
        </button>
        <button
          className="youjp-tool"
          onClick={() => setShowSettings((value) => !value)}
          title="Ajustes de subtítulos (Alt+S)"
          aria-label="Ajustes de subtítulos"
        >
          ⚙
        </button>
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
          <span title="audio pendiente en la cola del backend">
            buf <b>{metrics.audio_buffer_ms.toFixed(0)}</b> ms
          </span>
          <span
            title="tramas de audio descartadas — debe quedarse en cero"
            className={metrics.dropped_audio_chunks > 0 ? 'youjp-bad' : undefined}
          >
            drop <b>{metrics.dropped_audio_chunks}</b>
          </span>
          <span title="pasadas de Whisper / saltadas por el VAD">
            pas {metrics.passes}/<b>{metrics.skipped_silent}</b>
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
    </>
  );
}
