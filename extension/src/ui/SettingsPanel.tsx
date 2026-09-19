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
import { DEFAULT_SETTINGS } from '../settings';
import type { TargetLanguage } from '../protocol';

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
    <div className="youjp-setting">
      <div className="youjp-setting-label">
        {label}
        {hint && <span className="youjp-setting-hint">{hint}</span>}
      </div>
      {children}
    </div>
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
        <button
          key={key}
          className={key === value ? 'youjp-choice-btn youjp-choice-btn--on' : 'youjp-choice-btn'}
          onClick={() => onPick(key)}
          title={hint || undefined}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function SettingsPanel({ settings, onChange, onClose }: Props) {
  return (
    <div className="youjp-settings" role="dialog" aria-label="Ajustes de subtítulos">
      <div className="youjp-settings-head">
        <span>Ajustes</span>
        <button className="youjp-card-close" onClick={onClose} aria-label="Cerrar">
          ×
        </button>
      </div>

      <div className="youjp-settings-body">
        <Row label="Tamaño del japonés" hint={`${settings.jaSize} px`}>
          <input
            id="youjp-ja-size"
            type="range"
            min={16}
            max={56}
            step={2}
            value={settings.jaSize}
            onChange={(e) => onChange({ jaSize: Number(e.target.value) })}
          />
        </Row>

        <Row label="Tamaño de la traducción" hint={`${settings.translationSize} px`}>
          <input
            id="youjp-es-size"
            type="range"
            min={12}
            max={44}
            step={1}
            value={settings.translationSize}
            onChange={(e) => onChange({ translationSize: Number(e.target.value) })}
          />
        </Row>

        {settings.position ? (
          <Row label="Posición" hint="colocada a mano">
            <button className="youjp-reset" onClick={() => onChange({ position: null })}>
              Volver abajo y centrado
            </button>
          </Row>
        ) : (
          <Row label="Altura sobre el borde" hint={`${settings.bottom} px`}>
            <input
              id="youjp-bottom"
              type="range"
              min={8}
              max={320}
              step={4}
              value={settings.bottom}
              onChange={(e) => onChange({ bottom: Number(e.target.value) })}
            />
          </Row>
        )}

        <Row label="Ancho máximo" hint={`${settings.width} %`}>
          <input
            id="youjp-width"
            type="range"
            min={40}
            max={100}
            step={2}
            value={settings.width}
            onChange={(e) => onChange({ width: Number(e.target.value) })}
          />
        </Row>

        <Row label="Furigana">
          <Choice options={FURIGANA} value={settings.furigana} onPick={(v) => onChange({ furigana: v })} />
        </Row>

        <Row label="Fondo">
          <Choice options={BACKDROP} value={settings.backdrop} onPick={(v) => onChange({ backdrop: v })} />
        </Row>

        <Row label="Traducir al" hint="Se aplica a las próximas frases; el historial conserva su idioma original.">
          <Choice options={TARGETS} value={settings.targetLanguage} onPick={(v) => onChange({ targetLanguage: v })} />
        </Row>

        <Row label="Mostrar">
          <Choice options={LANGUAGES} value={settings.languages} onPick={(v) => onChange({ languages: v })} />
        </Row>

        <Row label="Frases anteriores" hint={String(settings.history)}>
          <input
            id="youjp-history"
            type="range"
            min={0}
            max={3}
            step={1}
            value={settings.history}
            onChange={(e) => onChange({ history: Number(e.target.value) })}
          />
        </Row>

        <Row label="Texto en curso" hint="La cola gris que aún puede cambiar">
          <label className="youjp-switch">
            <input
              id="youjp-tentative"
              type="checkbox"
              checked={settings.showTentative}
              onChange={(e) => onChange({ showTentative: e.target.checked })}
            />
            <span>{settings.showTentative ? 'Visible' : 'Oculto'}</span>
          </label>
        </Row>

        <button className="youjp-reset" onClick={() => onChange(DEFAULT_SETTINGS)}>
          Restablecer
        </button>
      </div>
    </div>
  );
}
