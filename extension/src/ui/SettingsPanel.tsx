/**
 * Panel de ajustes del overlay.
 *
 * Vive encima del vídeo y aplica los cambios en vivo. Una pantalla de opciones
 * aparte no serviría para esto: ajustar el tamaño del texto a ciegas y volver a
 * mirar es adivinar, y lo que hace falta es ver el efecto sobre el fotograma
 * real.
 */

import type {
  BackdropMode,
  FuriganaMode,
  LanguageMode,
  OverlaySettings,
} from '../settings';
import { uiText } from '../i18n';
import { DEFAULT_SETTINGS } from '../settings';
import type { TargetLanguage } from '../protocol';
import { Icon } from './Icon';

interface Props {
  settings: OverlaySettings;
  onChange: (patch: Partial<OverlaySettings>) => void;
  onClose: () => void;
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

const LANGUAGES: Array<[LanguageMode, string, string]> = [
  ['both', 'Ambos', ''],
  ['ja', 'Solo japonés', 'Para practicar comprensión sin la muleta'],
  ['translation', 'Solo traducción', ''],
];

const TARGETS: Array<[TargetLanguage, string, string]> = [
  ['es', 'Español', 'Japonés → español'],
  ['en', 'English', 'Japanese → English'],
];


function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <fieldset className="youjp-setting" aria-label={label}>
      <div className="youjp-setting-label">
        {label}
        {hint && <span className="youjp-setting-hint">{hint}</span>}
      </div>
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

export function SettingsPanel({ settings, onChange, onClose }: Props) {
  const t = (es: string, en?: string) => uiText(settings.settingsLanguage, es, en);
  const translateOptions = <T extends string>(options: Array<[T, string, string]>): Array<[T, string, string]> =>
    options.map(([value, label, hint]) => [value, t(label), t(hint)]);
  return (
    <div className="youjp-settings" role="dialog" aria-label={t('Ajustes de subtítulos', 'Subtitle settings')}>
      <div className="youjp-settings-head">
        <span className="youjp-panel-mark" aria-hidden="true">調</span>
        <span className="youjp-panel-heading"><span>{t('Ajustes', 'Settings')}</span>
          <small>{t('A tu manera. En tiempo real.', 'Your way. In real time.')}</small></span>
        <button type="button" className="youjp-card-close" onClick={onClose} aria-label={t('Cerrar', 'Close')}>
          <Icon name="close" />
        </button>
      </div>

      <div className="youjp-settings-body">
        <fieldset className="youjp-setting-section">
          <legend>{t('Tu experiencia', 'Your experience')}</legend>
        <Row label={t('Idioma de la interfaz', 'Interface language')}>
          <Choice options={[[ 'es', 'Español', '' ], [ 'en', 'English', '' ]]}
            value={settings.settingsLanguage} onPick={(v) => onChange({ settingsLanguage: v })} />
        </Row>
        </fieldset>
        <fieldset className="youjp-setting-section">
          <legend>{t('Lectura y posición', 'Reading and position')}</legend>
        <Row label={t('Tamaño del japonés', 'Japanese text size')} hint={`${settings.jaSize} px`}>
          <input
            id="youjp-ja-size"
            aria-label={t('Tamaño del japonés', 'Japanese text size')}
            type="range"
            min={16}
            max={56}
            step={2}
            value={settings.jaSize}
            onChange={(e) => onChange({ jaSize: Number(e.target.value) })}
          />
        </Row>

        <Row label={t('Tamaño de la traducción', 'Translation text size')} hint={`${settings.translationSize} px`}>
          <input
            id="youjp-es-size"
            aria-label={t('Tamaño de la traducción', 'Translation text size')}
            type="range"
            min={12}
            max={44}
            step={1}
            value={settings.translationSize}
            onChange={(e) => onChange({ translationSize: Number(e.target.value) })}
          />
        </Row>

        <Row label={t('Texto del historial', 'History text size')} hint={`${settings.transcriptSize} px`}>
          <input
            id="youjp-transcript-size"
            aria-label={t('Texto del historial', 'History text size')}
            type="range"
            min={12}
            max={32}
            step={1}
            value={settings.transcriptSize}
            onChange={(e) => onChange({ transcriptSize: Number(e.target.value) })}
          />
        </Row>

        {settings.position ? (
          <Row label={t('Posición', 'Position')} hint={t('colocada a mano', 'manually positioned')}>
            <button type="button" className="youjp-reset" onClick={() => onChange({ position: null })}>
              {t('Volver abajo y centrado', 'Reset to bottom center')}
            </button>
          </Row>
        ) : (
          <Row label={t('Altura sobre el borde', 'Distance from bottom')} hint={`${settings.bottom} px`}>
            <input
              id="youjp-bottom"
              aria-label={t('Altura sobre el borde', 'Distance from bottom')}
              type="range"
              min={8}
              max={320}
              step={4}
              value={settings.bottom}
              onChange={(e) => onChange({ bottom: Number(e.target.value) })}
            />
          </Row>
        )}

        <Row label={t('Ancho máximo', 'Maximum width')} hint={`${settings.width} %`}>
          <input
            id="youjp-width"
            aria-label={t('Ancho máximo', 'Maximum width')}
            type="range"
            min={40}
            max={100}
            step={2}
            value={settings.width}
            onChange={(e) => onChange({ width: Number(e.target.value) })}
          />
        </Row>

        </fieldset>
        <fieldset className="youjp-setting-section">
          <legend>{t('Idioma y ayudas', 'Language and reading aids')}</legend>
        <Row label="Furigana">
          <Choice options={translateOptions(FURIGANA)} value={settings.furigana} onPick={(v) => onChange({ furigana: v })} />
        </Row>

        <Row label={t('Fondo', 'Background')}>
          <Choice options={translateOptions(BACKDROP)} value={settings.backdrop} onPick={(v) => onChange({ backdrop: v })} />
        </Row>

        <Row label={t('Traducir al', 'Translate into')} hint={t('Se aplica a las próximas frases; el historial conserva su idioma original.', 'Applies to new sentences; history keeps its original language.')}>
          <Choice options={translateOptions(TARGETS)} value={settings.targetLanguage} onPick={(v) => onChange({ targetLanguage: v })} />
        </Row>

        <Row label={t('Mostrar', 'Show')}>
          <Choice options={translateOptions(LANGUAGES)} value={settings.languages} onPick={(v) => onChange({ languages: v })} />
        </Row>

        <Row label={t('Frases anteriores', 'Previous sentences')} hint={String(settings.history)}>
          <input
            id="youjp-history"
            aria-label={t('Frases anteriores', 'Previous sentences')}
            type="range"
            min={0}
            max={3}
            step={1}
            value={settings.history}
            onChange={(e) => onChange({ history: Number(e.target.value) })}
          />
        </Row>

        <Row label={t('Texto en curso', 'Partial text')} hint={t('La cola gris que aún puede cambiar', 'The gray text that may still change')}>
          <label className="youjp-switch">
            <input
              id="youjp-tentative"
              type="checkbox"
              checked={settings.showTentative}
              onChange={(e) => onChange({ showTentative: e.target.checked })}
            />
            <span>{settings.showTentative ? t('Visible', 'Visible') : t('Oculto', 'Hidden')}</span>
          </label>
        </Row>

        </fieldset>
        <button type="button" className="youjp-reset" onClick={() => onChange({ ...DEFAULT_SETTINGS, settingsLanguage: settings.settingsLanguage })}>
          {t('Restablecer', 'Reset')}
        </button>
        <p className="youjp-capture-hint">
          {t('Texto dentro de imágenes:', 'Text in images:')} <kbd>Alt</kbd> + <kbd>{t('Mayús', 'Shift')}</kbd> + <kbd>S</kbd>
          {' '}{t('para seleccionar y traducir una zona visible.', 'to select and translate a visible region.')}
        </p>
      </div>
    </div>
  );
}
