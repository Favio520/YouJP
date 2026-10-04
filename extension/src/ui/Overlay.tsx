import { uiText } from '../i18n';
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
import type { AsrFinal, AsrPartial, MetricsTick } from '../protocol';
import type { CaptureStatus, ExtensionMessage } from '../messages';
import {
  DEFAULT_SETTINGS,
  loadSettings,
  normalizeSettings,
  onSettingsChanged,
  saveSettings,
  toCssVars,
  type OverlaySettings,
} from '../settings';
import { currentVideoId, findVideo, isLive } from '../player';
import {
  cueIndexAt, cueToLine, requestVideo, type VideoSnapshot,
} from '../video';
import type { TargetLanguage } from '../protocol';
import { SettingsPanel } from './SettingsPanel';
import { Subtitle } from './Subtitle';
import { TranscriptPanel } from './TranscriptPanel';
import type { Line, Selection } from './types';
import { useDrag } from './useDrag';
import { WordInspector } from './WordInspector';
import { Icon } from './Icon';
import { UI_STATE_EVENT, type UiState } from './uiState';

const MAX_LINES = 4; // la actual mas tres de historial en el overlay

/** Frases que se conservan para el historial completo. Una sesion larga de
 *  estudio son unos cientos; mas alla no se consulta y solo ocupa. */
const MAX_LOG = 300;

/** Tras el final de una frase, cuánto sigue en pantalla si no llega otra. */
const CUE_LINGER_MS = 2500;
const POLL_MS = 1500;
/** Cuánto dura el aviso de "vídeo listo". */
const READY_TOAST_MS = 4000;

const requestVideoToggle = () => window.dispatchEvent(new Event('youjp:prepare-video'));

interface Prepared {
  phase: 'none' | 'working' | 'ready' | 'error';
  videoId: string;
  lines: Line[];
  progress: number;
  source: string;
  message: string;
}

const noPrepared = (videoId: string): Prepared =>
  ({ phase: 'none', videoId, lines: [], progress: 0, source: '', message: '' });

const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

const GRAMMAR_KEYS: Array<[string, string]> = [
  ['n', 'sustantivo'], ['v', 'verbo'], ['adj', 'adjetivo'], ['adv', 'adverbio'], ['p', 'partícula'],
];

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
  const [liveHistory, setHistory] = useState<Line[]>([]);
  const [metrics, setMetrics] = useState<MetricsTick | null>(null);
  const [showMetrics, setShowMetrics] = useState(false);
  const [rateWarning, setRateWarning] = useState<number | null>(null);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [settings, setSettings] = useState<OverlaySettings>(DEFAULT_SETTINGS);
  const settingsRef = useRef(settings);
  const settingsVersion = useRef(0);
  const [showSettings, setShowSettings] = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  const lastFinal = useRef(0);

  const closeCard = useCallback(() => setSelected(null), []);

  // -- Vídeo completo traducido de antemano ------------------------------------
  const [videoId, setVideoId] = useState(currentVideoId);
  const [prepared, setPrepared] = useState<Prepared>(() => noPrepared(currentVideoId()));
  const preparedRef = useRef(prepared);
  preparedRef.current = prepared;
  const [active, setActive] = useState({ index: -1, gap: true });
  // Subtítulos del vídeo ya traducido: se pueden apagar sin perder el trabajo.
  const [preparedOn, setPreparedOn] = useState(true);
  const [readyToast, setReadyToast] = useState(false);
  const previousPhase = useRef<Prepared['phase']>('none');
  const liveActive = status !== 'idle' || liveHistory.length > 0;

  const applySnapshot = useCallback((snap: VideoSnapshot, id: string, target: TargetLanguage) => {
    setPrepared((prev) => {
      if (prev.videoId !== id) return prev;
      // Idempotente: una respuesta repetida o atrasada no duplica frases.
      let lines = prev.lines;
      for (const cue of snap.cues ?? []) {
        if (cue.i !== lines.length) continue;
        if (lines === prev.lines) lines = prev.lines.slice();
        lines.push(cueToLine(cue, target));
      }
      const phase = snap.status === 'none' ? 'none' : snap.status === 'error' ? 'error'
        : snap.status === 'done' ? 'ready' : 'working';
      return { ...prev, phase, lines, progress: snap.progress ?? prev.progress,
        source: snap.source ?? '', message: snap.error ?? '' };
    });
  }, []);

  useEffect(() => {
    const onVideo = () => setVideoId(currentVideoId());
    window.addEventListener('youjp:video', onVideo);
    return () => window.removeEventListener('youjp:video', onVideo);
  }, []);

  // Al abrir un vídeo (o cambiar el idioma) se pregunta si ya está preparado:
  // si lo está, se ve sincronizado sin hacer nada.
  useEffect(() => {
    setPrepared(noPrepared(videoId));
    setActive({ index: -1, gap: true });
    setPreparedOn(true);
    if (!videoId) return;
    let stale = false;
    const target = settings.targetLanguage;
    requestVideo('poll', videoId, target)
      .then((snap) => { if (!stale) applySnapshot(snap, videoId, target); })
      .catch(() => {});
    return () => { stale = true; };
  }, [videoId, settings.targetLanguage, applySnapshot]);

  useEffect(() => {
    if (prepared.phase !== 'working') return;
    const id = prepared.videoId;
    const target = settings.targetLanguage;
    let stopped = false;
    let busy = false;
    const tick = async () => {
      if (busy) return;
      busy = true;
      try {
        const snap = await requestVideo('poll', id, target, preparedRef.current.lines.length);
        if (!stopped) applySnapshot(snap, id, target);
      } catch (error) {
        if (!stopped) setPrepared((prev) => prev.videoId === id
          ? { ...prev, phase: 'error', message: errorText(error) } : prev);
      } finally {
        busy = false;
      }
    };
    const timer = setInterval(() => void tick(), POLL_MS);
    return () => { stopped = true; clearInterval(timer); };
  }, [prepared.phase, prepared.videoId, settings.targetLanguage, applySnapshot]);

  // Botón de la barra del reproductor: prepara el vídeo o cancela si ya está en marcha.
  useEffect(() => {
    const toggle = async () => {
      const id = currentVideoId();
      const target = settingsRef.current.targetLanguage;
      const current = preparedRef.current;
      if (!id) return;
      if (current.phase === 'ready') {
        setPreparedOn((value) => !value);
        return;
      }
      if (isLive(findVideo())) {
        setPrepared({ ...noPrepared(id), phase: 'error',
          message: 'Es un directo: se traduce en tiempo real con el icono de YouJP.' });
        return;
      }
      if (current.phase === 'working') {
        setPrepared(noPrepared(id));
        await requestVideo('cancel', id, target).catch(() => {});
        return;
      }
      setPrepared({ ...noPrepared(id), phase: 'working' });
      try {
        applySnapshot(await requestVideo('prepare', id, target), id, target);
      } catch (error) {
        setPrepared({ ...noPrepared(id), phase: 'error', message: errorText(error) });
      }
    };
    const listener = () => void toggle();
    window.addEventListener('youjp:prepare-video', listener);
    return () => window.removeEventListener('youjp:prepare-video', listener);
  }, [applySnapshot]);

  useEffect(() => {
    const finished = previousPhase.current === 'working' && prepared.phase === 'ready';
    previousPhase.current = prepared.phase;
    if (!finished) return;
    setReadyToast(true);
    const timer = setTimeout(() => setReadyToast(false), READY_TOAST_MS);
    return () => clearTimeout(timer);
  }, [prepared.phase]);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent<UiState>(UI_STATE_EVENT, {
      detail: {
        settingsOpen: showSettings,
        video: { phase: prepared.phase, progress: prepared.progress, enabled: preparedOn, message: prepared.message },
      },
    }));
  }, [showSettings, prepared.phase, prepared.progress, prepared.message, preparedOn]);

  // Qué frase toca según el reproductor. Se compara antes de guardar: el
  // sondeo corre varias veces por segundo y casi siempre no cambia nada.
  useEffect(() => {
    if (prepared.lines.length === 0 || liveActive || !preparedOn) return;
    const update = () => {
      const video = findVideo();
      if (!video) return;
      const time = video.currentTime * 1000;
      const index = cueIndexAt(prepared.lines, time);
      const gap = index < 0 || time > (prepared.lines[index]?.mediaEndMs ?? 0) + CUE_LINGER_MS;
      setActive((current) => current.index === index && current.gap === gap ? current : { index, gap });
    };
    update();
    const timer = setInterval(update, 150);
    return () => clearInterval(timer);
  }, [prepared.lines, liveActive, preparedOn]);

  const patchSettings = useCallback((patch: Partial<OverlaySettings>) => {
    const next = normalizeSettings({ ...settingsRef.current, ...patch });
    settingsRef.current = next;
    settingsVersion.current += 1;
    setSettings(next);
    void saveSettings(next);
  }, []);

  useEffect(() => {
    let active = true;
    const version = settingsVersion.current;
    const apply = (next: OverlaySettings) => {
      settingsRef.current = next;
      settingsVersion.current += 1;
      setSettings(next);
    };
    const unsubscribe = onSettingsChanged(apply);
    void loadSettings().then((next) => {
      if (active && settingsVersion.current === version) apply(next);
    });
    return () => { active = false; unsubscribe(); };
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
          if (message.status === 'reconnecting' || message.status === 'connecting') {
            setPartial(null);
            setMetrics(null);
          }
          if (message.status === 'idle' || message.status === 'starting') {
            lastFinal.current = 0;
            setPartial(null);
            setHistory([]);
            setMetrics(null);
            setModel('');
            // La consulta sigue abierta, pero ya no señala una frase de la
            // sesión anterior cuando los ID se reinician desde cero.
            setSelected((current) => current ? { ...current, lineId: -1 } : null);
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
                translation: '',
                target: null,
                tokens: [],
                mediaStartMs: final.media_start_ms,
              },
            ].slice(-MAX_LOG),
          );
          setPartial(null);
          break;
        }
        case 'subtitle.translation': {
          const { segment_id, text, text_es, target = 'es' } = message.payload;
          // La traducción puede llegar cuando la frase ya ha salido del
          // historial: en ese caso no hay nada que actualizar y se descarta.
          setHistory((prev) =>
            prev.map((line) => (line.id === segment_id
              ? { ...line, translation: text ?? text_es ?? '', target } : line)),
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
    const clearPartial = () => setPartial(null);
    const changeVideo = () => {
      lastFinal.current = 0;
      setPartial(null);
      setHistory([]);
      setMetrics(null);
      setSelected((current) => current ? { ...current, lineId: -1 } : null);
    };
    window.addEventListener('youjp:flush', clearPartial);
    window.addEventListener('youjp:video', changeVideo);
    return () => {
      window.removeEventListener('youjp:flush', clearPartial);
      window.removeEventListener('youjp:video', changeVideo);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const shortcut = event.altKey && !event.shiftKey && !event.ctrlKey && !event.metaKey;
      if (shortcut && event.code === 'KeyM') {
        event.preventDefault();
        setShowMetrics((value) => !value);
      }
      if (shortcut && event.code === 'KeyS') {
        event.preventDefault();
        setShowSettings((value) => !value);
      }
      if (shortcut && event.code === 'KeyH') {
        event.preventDefault();
        setShowTranscript((value) => !value);
      }
      if (event.key === 'Escape') {
        setSelected(null);
        setShowSettings(false);
        setShowTranscript(false);
        setShowMetrics(false);
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, []);

  useEffect(() => {
    const openSettings = () => setShowSettings((value) => !value);
    window.addEventListener('youjp:toggle-settings', openSettings);
    return () => window.removeEventListener('youjp:toggle-settings', openSettings);
  }, []);

  useEffect(() => {
    const listener = (event: Event) => {
      const rate = (event as CustomEvent<number>).detail;
      setRateWarning(Math.abs(rate - 1) > 0.01 ? rate : null);
    };
    window.addEventListener('youjp:rate', listener);
    return () => window.removeEventListener('youjp:rate', listener);
  }, []);

  const t = (value: string) => uiText(settings.settingsLanguage, value);
  const videoShown = prepared.phase !== 'none' && !(prepared.phase === 'ready' && !preparedOn);
  const hasCaptureUi = liveActive || videoShown;
  if (!hasCaptureUi && !showSettings && !showTranscript && !selected) return null;

  // En un vídeo preparado las "frases anteriores" son las que ya han pasado, y
  // el historial es el vídeo entero: así se puede saltar a cualquier punto.
  const preparedMode = !liveActive && preparedOn && prepared.lines.length > 0;
  const history = preparedMode ? prepared.lines.slice(0, active.index + 1) : liveHistory;
  const transcriptLines = preparedMode ? prepared.lines : liveHistory;
  const visible = preparedMode && active.gap ? []
    : settings.history >= MAX_LINES ? history : history.slice(-(settings.history + 1));
  const progressPercent = Math.round(prepared.progress * 100);
  const preparingLabel = prepared.source === 'captions' ? 'con el transcript de YouTube'
    : prepared.source === 'whisper' ? 'transcribiendo el audio' : '';
  const committed = partial?.committed ?? '';
  const tentative = settings.showTentative ? (partial?.tentative ?? '') : '';
  const showJa = settings.languages !== 'translation';
  const showTranslation = settings.languages !== 'ja';

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
          withDictionary={selected !== null && !settings.wordPanelPosition}
          language={settings.settingsLanguage}
          lines={transcriptLines}
          activeId={preparedMode && active.index >= 0 ? active.index : undefined}
          position={settings.transcriptPosition}
          onMove={(transcriptPosition) => patchSettings({ transcriptPosition })}
          onResetPosition={() => patchSettings({ transcriptPosition: null })}
          onSeek={seek}
          onClose={() => setShowTranscript(false)}
          showTranslation={showTranslation}
          textSize={settings.transcriptSize}
          furigana={settings.furigana}
          selected={selected}
          onSelect={(lineId, token) => setSelected({ lineId, token, from: 'transcript' })}
        />
      )}

      {showSettings && (
        <div className="youjp-settings-dock">
          <SettingsPanel
            settings={settings}
            onChange={patchSettings}
            onClose={() => setShowSettings(false)}
            video={{ phase: prepared.phase, progress: prepared.progress, source: prepared.source,
              enabled: preparedOn, message: prepared.message, live: liveActive }}
            onVideoAction={requestVideoToggle}
          />
        </div>
      )}

      {selected && (
        <WordInspector
          withHistory={showTranscript && !settings.transcriptPosition}
          language={settings.settingsLanguage}
          token={selected.token}
          target={settings.targetLanguage}
          position={settings.wordPanelPosition}
          onMove={(wordPanelPosition) => patchSettings({ wordPanelPosition })}
          onResetPosition={() => patchSettings({ wordPanelPosition: null })}
          onClose={closeCard}
        />
      )}

      {hasCaptureUi && (
      <div
        className={[
          'youjp-root',
          `youjp-skin--${settings.skin}`,
          settings.skin !== 'paper' ? `youjp-bg--${settings.backdrop}` : '',
          libre ? 'youjp-root--free' : '',
          dragging ? 'youjp-root--dragging' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        style={estilo}
      >
      {liveActive && status !== 'running' && (
        <div className={`youjp-status youjp-status--${status}`}>
          <span className="youjp-dot" />
          {t(STATUS_LABEL[status])}
          {detail && <span className="youjp-detail">{t(detail)}</span>}
        </div>
      )}

      {!liveActive && prepared.phase === 'working' && (
        <div className="youjp-status youjp-status--working" role="status">
          <span className="youjp-dot" />
          <span className="youjp-status-text">
            {t('Traduciendo el vídeo…')} {progressPercent > 0 && <b>{progressPercent}%</b>}
            {preparingLabel && <span className="youjp-detail">{t(preparingLabel)}</span>}
          </span>
          <button type="button" className="youjp-status-action" onClick={requestVideoToggle}>
            {t('Detener')}
          </button>
          <span className="youjp-status-meter" aria-hidden="true">
            <i style={{ width: `${Math.max(3, progressPercent)}%` }} />
          </span>
        </div>
      )}

      {!liveActive && prepared.phase === 'ready' && readyToast && (
        <div className="youjp-status youjp-status--ready" role="status">
          <span className="youjp-dot" />
          {t('Vídeo traducido')}
          <span className="youjp-detail">{t('Los subtítulos siguen el vídeo.')}</span>
        </div>
      )}

      {!liveActive && prepared.phase === 'error' && (
        <div className="youjp-status youjp-status--error" role="alert">
          <span className="youjp-status-text">{t(prepared.message)}</span>
          <button type="button" className="youjp-status-action" onClick={requestVideoToggle}>
            {t('Reintentar')}
          </button>
        </div>
      )}

      {rateWarning !== null && (
        <div className="youjp-status youjp-status--error">
          {settings.settingsLanguage === 'en'
            ? `Speed ${rateWarning}× — transcription is paused. Faster audio reduces accuracy and breaks timing.`
            : `Velocidad ${rateWarning}× — la transcripción está pausada. El audio acelerado se transcribe mal y descuadra los tiempos.`}
        </div>
      )}

      {settings.skin === 'grammar' && (
        <ul className="youjp-legend" aria-label={t('Categorías gramaticales')}>
          {GRAMMAR_KEYS.map(([key, label]) => (
            <li key={key} data-k={key}>{t(label)}</li>
          ))}
        </ul>
      )}

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
                    selectedIndex={selected?.from === 'subtitles' && selected.lineId === line.id
                      ? selected.token.i : null}
                    onSelect={(token) => setSelected({ lineId: line.id, token, from: 'subtitles' })}
                  />
                </p>
              )}
              {showTranslation && line.target === settings.targetLanguage && line.translation && (
                <p className="youjp-es" lang={line.target}>{line.translation}</p>
              )}
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
        <button type="button"
          className="youjp-tool youjp-grip"
          onMouseDown={empezar}
          title={t('Arrastrar para mover los subtítulos')}
          aria-label={t('Mover los subtítulos')}
        >
          <Icon name="move" />
        </button>
        <button type="button"
          className="youjp-tool"
          onClick={() => setShowTranscript((value) => !value)}
          title={`${t('Historial de la sesión')} · ${transcriptLines.length} ${t('frases')} (Alt+H)`}
          aria-label={t('Historial de la sesión')}
          aria-expanded={showTranscript}
        >
          <Icon name="history" />
        </button>
        <button type="button"
          className="youjp-tool"
          onClick={() => setShowSettings((value) => !value)}
          title={`${t('Ajustes de subtítulos')} (Alt+S)`}
          aria-label={t('Ajustes de subtítulos')}
          aria-expanded={showSettings}
        >
          <Icon name="settings" />
        </button>
      </div>

      {showMetrics && metrics && (
        <div className="youjp-metrics">
          <span title={t('latencia extremo a extremo')}>
            e2e <b>{metrics.end_to_end_ms_p50.toFixed(0)}</b>/
            {metrics.end_to_end_ms_p95.toFixed(0)} ms
          </span>
          <span title={t('inferencia de Whisper')}>
            asr <b>{metrics.whisper_processing_ms_p50.toFixed(0)}</b> ms
          </span>
          <span title={t('análisis morfológico y consulta de diccionario')}>
            nlp <b>{metrics.nlp_ms_p50.toFixed(1)}</b> ms
          </span>
          <span title={t('traducción: latencia p50 y frases traducidas')}>
            mt <b>{metrics.translation_latency_ms_p50.toFixed(0)}</b> ms ·{' '}
            {metrics.translations}
            {metrics.dropped_translations > 0 && (
              <span className="youjp-bad"> (−{metrics.dropped_translations})</span>
            )}
          </span>
          <span title={t('audio pendiente en la cola del backend')}>
            buf <b>{metrics.audio_buffer_ms.toFixed(0)}</b> ms
          </span>
          <span
            title={t('tramas de audio descartadas — debe quedarse en cero')}
            className={metrics.dropped_audio_chunks > 0 ? 'youjp-bad' : undefined}
          >
            drop <b>{metrics.dropped_audio_chunks}</b>
          </span>
          <span title={t('pasadas de Whisper / saltadas por el VAD')}>
            {t('pas')} {metrics.passes}/<b>{metrics.skipped_silent}</b>
          </span>
          <span
            title={t('VRAM usada — por debajo de 500 MiB libres el sistema empieza a degradarse')}
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
      )}
    </>
  );
}
