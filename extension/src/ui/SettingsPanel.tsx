/**
 * Panel de ajustes del overlay.
 *
 * Vive encima del vídeo y aplica los cambios en vivo. Una pantalla de opciones
 * aparte no serviría para esto: ajustar el tamaño del texto a ciegas y volver a
 * mirar es adivinar, y lo que hace falta es ver el efecto sobre el fotograma
 * real. Cuando no hay subtítulos en pantalla, la vista previa de arriba cumple
 * ese papel con una frase de ejemplo.
 */

import type {
  BackdropMode,
  FuriganaMode,
  LanguageMode,
  OverlaySettings,
  SkinMode,
} from '../settings';
import { uiText, type UiLanguage } from '../i18n';
import { DEFAULT_SETTINGS } from '../settings';
import type { TargetLanguage } from '../protocol';
import { Icon } from './Icon';
import type { VideoPhase } from './uiState';

export interface VideoPanelState {
  phase: VideoPhase;
  progress: number;
  source: string;
  enabled: boolean;
  message: string;
  /** Hay una captura en directo en marcha: manda sobre el vídeo preparado. */
  live: boolean;
}

interface Props {
  settings: OverlaySettings;
  onChange: (patch: Partial<OverlaySettings>) => void;
  onClose: () => void;
  video: VideoPanelState;
  /** Traducir, detener, apagar o encender: depende del estado. */
  onVideoAction: () => void;
}

const FURIGANA: Array<[FuriganaMode, string, string]> = [
  ['off', 'No', 'Sin anotaciones de lectura'],
  ['auto', 'Automática', 'Solo en palabras poco frecuentes: así los kanji comunes se siguen aprendiendo'],
  ['all', 'Siempre', 'En todos los kanji'],
];

const BACKDROP: Array<[BackdropMode, string, string]> = [
  ['none', 'Ninguno', 'Solo contorno; deja ver todo el vídeo'],
  ['soft', 'Suave', 'Banda difuminada bajo el texto'],
  ['solid', 'Sólido', 'Máximo contraste sobre fondos claros o con mucho movimiento'],
];

const SKINS: Array<[SkinMode, string, string]> = [
  ['ribbon', 'Cinta', 'Banda oscura que se lee sobre cualquier vídeo sin taparlo'],
  ['paper', 'Papel', 'Tarjeta de papel con tinta, como el lanzador'],
  ['grammar', 'Gramática', 'Cada palabra subrayada según su categoría, sobre un fondo suave'],
];

const LANGUAGES: Array<[LanguageMode, string, string]> = [
  ['both', 'Ambos', ''],
  ['ja', 'Solo japonés', 'Para practicar comprensión sin la muleta'],
  ['translation', 'Solo traducción', ''],
];

const TARGETS: Array<[TargetLanguage, string, string]> = [
  ['es', 'Español', 'Japonés → español'],
  ['en', 'English', 'Japanese → English'],
];

function Row({ label, value, hint, children }: {
  label: string; value?: string; hint?: string; children: React.ReactNode;
}) {
  return (
    <fieldset className="youjp-setting" aria-label={label}>
      <div className="youjp-setting-label">
        <span>{label}</span>
        {value && <output className="youjp-setting-value">{value}</output>}
      </div>
      {hint && <span className="youjp-setting-hint">{hint}</span>}
      {children}
    </fieldset>
  );
}

function Choice<T extends string>({
  options,
  value,
  onPick,
}: {
  options: Array<[T, string, string]>;
  value: T;
  onPick: (v: T) => void;
}) {
  return (
    <div className="youjp-choice">
      {options.map(([key, label, hint]) => (
        <button type="button"
          key={key}
          className={key === value ? 'youjp-choice-btn youjp-choice-btn--on' : 'youjp-choice-btn'}
          onClick={() => onPick(key)}
          title={hint || undefined}
          aria-pressed={key === value}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function Slider({ id, label, unit, min, max, step, value, onChange }: {
  id: string; label: string; unit: string; min: number; max: number; step: number;
  value: number; onChange: (value: number) => void;
}) {
  return (
    <Row label={label} value={`${value} ${unit}`}>
      <input id={id} aria-label={label} type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
    </Row>
  );
}

/** Frase de ejemplo con los ajustes actuales: tamaño, furigana, fondo e idiomas. */
function Preview({ settings, label }: { settings: OverlaySettings; label: string }) {
  const showJa = settings.languages !== 'translation';
  const showTranslation = settings.languages !== 'ja';
  // Escala fija para que 56 px quepan en el panel sin cambiar las proporciones.
  const scale = 0.5;
  const sample: Array<{ text: string; kana?: string; common?: boolean; k: string }> = [
    { text: '今日', kana: 'きょう', common: true, k: 'n' }, { text: 'は', k: 'p' },
    { text: 'とても', k: 'adv' }, { text: '寒', kana: 'さむ', common: false, k: 'adj' },
    { text: 'い', k: 'adj' }, { text: 'です', k: 'aux' }, { text: 'ね', k: 'p' },
  ];
  const reading = (word: (typeof sample)[number]) =>
    word.kana && (settings.furigana === 'all' || (settings.furigana === 'auto' && !word.common))
      ? <ruby>{word.text}<rt>{word.kana}</rt></ruby> : word.text;
  // Cinta y Gramática comparten el ajuste de fondo; Papel ya es su propio fondo.
  const boxClass = settings.skin === 'paper' ? 'youjp-preview-box--paper'
    : `youjp-preview-box--${settings.skin} youjp-preview-box--${settings.backdrop}`;
  return (
    <div className="youjp-preview" aria-hidden="true">
      <span className="youjp-preview-label">{label}</span>
      <div className={`youjp-preview-box ${boxClass}`}>
        {showJa && (
          <p className="youjp-preview-ja" style={{ fontSize: settings.jaSize * scale }}>
            {sample.map((word) => <span key={word.text} className="youjp-preview-word" data-k={word.k}>{reading(word)}</span>)}。
          </p>
        )}
        {showTranslation && (
          <p className="youjp-preview-tr" style={{ fontSize: settings.translationSize * scale }}>
            {settings.targetLanguage === 'es' ? 'Hoy hace mucho frío, ¿verdad?' : "It's very cold today, isn't it?"}
          </p>
        )}
      </div>
    </div>
  );
}

/** Estado del vídeo actual: qué está pasando y qué hace el botón. */
function VideoCard({ video, onAction, language, t }: {
  video: VideoPanelState; onAction: () => void; language: UiLanguage; t: (es: string, en?: string) => string;
}) {
  const percent = Math.round(video.progress * 100);
  let tone: 'idle' | 'work' | 'ready' | 'off' | 'error' | 'live' = 'idle';
  let title = t('Traducir este vídeo', 'Translate this video');
  let detail = t('Lo traduce entero antes de verlo, con los subtítulos al compás. No sirve para directos.',
    'Translates it all before you watch, with subtitles in time. Not for live streams.');
  let action = t('Traducir el vídeo', 'Translate the video');

  if (video.live) {
    tone = 'live';
    title = t('Traducción en directo activa', 'Live translation is on');
    detail = t('Para detenerla, pulsa el icono de YouJP del navegador.', 'To stop it, click the YouJP icon in the browser.');
  } else if (video.phase === 'working') {
    tone = 'work';
    title = `${t('Traduciendo el vídeo…', 'Translating the video…')}${percent > 0 ? ` ${percent} %` : ''}`;
    detail = video.source === 'captions' ? t('Usando el transcript de YouTube.', 'Using the YouTube transcript.')
      : video.source === 'whisper' ? t('Transcribiendo el audio en tu equipo.', 'Transcribing the audio on your computer.')
        : t('Preparando el vídeo.', 'Getting the video ready.');
    action = t('Detener', 'Stop');
  } else if (video.phase === 'ready' && video.enabled) {
    tone = 'ready';
    title = t('Vídeo traducido', 'Video translated');
    detail = t('Los subtítulos siguen el vídeo. Puedes apagarlos y volver a encenderlos.', 'Subtitles follow the video. You can turn them off and on again.');
    action = t('Apagar subtítulos', 'Turn subtitles off');
  } else if (video.phase === 'ready') {
    tone = 'off';
    title = t('Subtítulos apagados', 'Subtitles off');
    detail = t('El vídeo sigue traducido y guardado.', 'The video stays translated and saved.');
    action = t('Encender subtítulos', 'Turn subtitles on');
  } else if (video.phase === 'error') {
    tone = 'error';
    title = t('No se pudo traducir', 'Could not translate');
    detail = uiText(language, video.message);
    action = t('Reintentar', 'Try again');
  }

  return (
    <div className={`youjp-video-card youjp-video-card--${tone}`}>
      <span className="youjp-video-state" aria-hidden="true" />
      <div className="youjp-video-text">
        <b>{title}</b>
        <span>{detail}</span>
        {tone === 'work' && (
          <span className="youjp-video-meter"><i style={{ width: `${Math.max(3, percent)}%` }} /></span>
        )}
      </div>
      {tone !== 'live' && (
        <button type="button" className={`youjp-video-action youjp-video-action--${tone}`} onClick={onAction}>
          {action}
        </button>
      )}
    </div>
  );
}

export function SettingsPanel({ settings, onChange, onClose, video, onVideoAction }: Props) {
  const t = (es: string, en?: string) => uiText(settings.settingsLanguage, es, en);
  const translateOptions = <T extends string>(options: Array<[T, string, string]>): Array<[T, string, string]> =>
    options.map(([value, label, hint]) => [value, t(label), t(hint)]);
  const reset = () => onChange({ ...DEFAULT_SETTINGS, settingsLanguage: settings.settingsLanguage });
  return (
    <div className="youjp-settings" role="dialog" aria-label={t('Ajustes de subtítulos', 'Subtitle settings')}>
      <div className="youjp-settings-head">
        <span className="youjp-panel-mark" aria-hidden="true">調</span>
        <span className="youjp-panel-heading"><span>{t('Ajustes', 'Settings')}</span>
          <small>{t('A tu manera. En tiempo real.', 'Your way. In real time.')}</small></span>
        <button type="button" className="youjp-card-close" onClick={reset}
          title={t('Restablecer ajustes', 'Reset settings')} aria-label={t('Restablecer ajustes', 'Reset settings')}>
          <Icon name="reset" />
        </button>
        <button type="button" className="youjp-card-close" onClick={onClose} aria-label={t('Cerrar', 'Close')}>
          <Icon name="close" />
        </button>
      </div>

      <Preview settings={settings} label={t('Vista previa', 'Preview')} />

      <div className="youjp-settings-body">
        <fieldset className="youjp-setting-section">
          <legend>{t('Este vídeo', 'This video')}</legend>
          <VideoCard video={video} onAction={onVideoAction} language={settings.settingsLanguage} t={t} />
        </fieldset>

        <fieldset className="youjp-setting-section">
          <legend>{t('Estilo de subtítulos', 'Subtitle style')}</legend>
          <div className="youjp-skins">
            {SKINS.map(([key, name, hint]) => (
              <button type="button" key={key} aria-pressed={settings.skin === key} title={t(hint)}
                className={settings.skin === key ? 'youjp-skin-card youjp-skin-card--on' : 'youjp-skin-card'}
                onClick={() => onChange({ skin: key })}>
                <span className={`youjp-skin-swatch youjp-skin-swatch--${key}`} aria-hidden="true">
                  <i /><i />
                </span>
                <span className="youjp-skin-name">{t(name, { ribbon: 'Ribbon', paper: 'Paper', grammar: 'Grammar' }[key])}</span>
              </button>
            ))}
          </div>
          <span className="youjp-setting-hint">{t(SKINS.find(([key]) => key === settings.skin)?.[2] ?? '')}</span>
        </fieldset>

        <fieldset className="youjp-setting-section">
          <legend>{t('Lectura y posición', 'Reading and position')}</legend>
          <Slider id="youjp-ja-size" label={t('Tamaño del japonés', 'Japanese text size')} unit="px"
            min={16} max={56} step={2} value={settings.jaSize} onChange={(jaSize) => onChange({ jaSize })} />
          <Slider id="youjp-es-size" label={t('Tamaño de la traducción', 'Translation text size')} unit="px"
            min={12} max={44} step={1} value={settings.translationSize}
            onChange={(translationSize) => onChange({ translationSize })} />
          <Slider id="youjp-transcript-size" label={t('Texto del historial', 'History text size')} unit="px"
            min={12} max={32} step={1} value={settings.transcriptSize}
            onChange={(transcriptSize) => onChange({ transcriptSize })} />

          {settings.position ? (
            <Row label={t('Posición', 'Position')} hint={t('colocada a mano', 'manually positioned')}>
              <button type="button" className="youjp-reset" onClick={() => onChange({ position: null })}>
                {t('Volver abajo y centrado', 'Reset to bottom center')}
              </button>
            </Row>
          ) : (
            <Slider id="youjp-bottom" label={t('Altura sobre el borde', 'Distance from bottom')} unit="px"
              min={8} max={320} step={4} value={settings.bottom} onChange={(bottom) => onChange({ bottom })} />
          )}

          <Slider id="youjp-width" label={t('Ancho máximo', 'Maximum width')} unit="%"
            min={40} max={100} step={2} value={settings.width} onChange={(width) => onChange({ width })} />
        </fieldset>

        <fieldset className="youjp-setting-section">
          <legend>{t('Idioma y ayudas', 'Language and reading aids')}</legend>
          <Row label="Furigana">
            <Choice options={translateOptions(FURIGANA)} value={settings.furigana} onPick={(v) => onChange({ furigana: v })} />
          </Row>

          {settings.skin !== 'paper' && (
            <Row label={t('Fondo', 'Background')}>
              <Choice options={translateOptions(BACKDROP)} value={settings.backdrop} onPick={(v) => onChange({ backdrop: v })} />
            </Row>
          )}

          <Row label={t('Traducir al', 'Translate into')}
            hint={t('Se aplica a las próximas frases; el historial conserva su idioma original.', 'Applies to new sentences; history keeps its original language.')}>
            <Choice options={translateOptions(TARGETS)} value={settings.targetLanguage} onPick={(v) => onChange({ targetLanguage: v })} />
          </Row>

          <Row label={t('Mostrar', 'Show')}>
            <Choice options={translateOptions(LANGUAGES)} value={settings.languages} onPick={(v) => onChange({ languages: v })} />
          </Row>

          <Slider id="youjp-history" label={t('Frases anteriores', 'Previous sentences')} unit=""
            min={0} max={3} step={1} value={settings.history} onChange={(history) => onChange({ history })} />

          <Row label={t('Texto en curso', 'Partial text')}
            hint={t('La cola gris que aún puede cambiar', 'The gray text that may still change')}>
            <label className="youjp-switch">
              <input
                id="youjp-tentative"
                type="checkbox"
                role="switch"
                aria-checked={settings.showTentative}
                checked={settings.showTentative}
                onChange={(e) => onChange({ showTentative: e.target.checked })}
              />
              <span className="youjp-switch-track" aria-hidden="true" />
              <span>{settings.showTentative ? t('Visible', 'Visible') : t('Oculto', 'Hidden')}</span>
            </label>
          </Row>
        </fieldset>

        <fieldset className="youjp-setting-section">
          <legend>{t('Interfaz', 'Interface')}</legend>
          <Row label={t('Idioma de la interfaz', 'Interface language')}>
            <Choice options={[['es', 'Español', ''], ['en', 'English', '']]}
              value={settings.settingsLanguage} onPick={(v) => onChange({ settingsLanguage: v })} />
          </Row>
        </fieldset>

        <p className="youjp-capture-hint">
          {t('Texto dentro de imágenes:', 'Text in images:')} <kbd>Alt</kbd> + <kbd>{t('Mayús', 'Shift')}</kbd> + <kbd>S</kbd>
          {' '}{t('para seleccionar y traducir una zona visible.', 'to select and translate a visible region.')}
        </p>
      </div>
    </div>
  );
}
