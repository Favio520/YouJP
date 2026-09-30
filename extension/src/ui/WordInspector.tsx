import { uiText, type UiLanguage } from '../i18n';
/** Consulta de diccionario que permanece abierta mientras avanzan los subtítulos. */

import type { TargetLanguage, Token } from '../protocol';
import { useDrag, type Position } from './useDrag';
import { WordCard } from './WordCard';

interface Props {
  language?: UiLanguage;
  token: Token;
  target: TargetLanguage;
  position: Position | null;
  onMove: (position: Position) => void;
  onResetPosition: () => void;
  onClose: () => void;
}

export function WordInspector({ token, target, position, onMove, onResetPosition, onClose, language = 'es' }: Props) {
  const t = (value: string) => uiText(language, value);
  const { dragging, preview, empezar } = useDrag(onMove);
  const actual = preview ?? position;
  const style = actual
    ? { left: `${actual.x}%`, top: `${actual.y}%`, right: 'auto', transform: 'translate(-50%, -50%)' }
    : undefined;

  return (
    <div
      className={`youjp-inspector${dragging ? ' youjp-inspector--dragging' : ''}`}
      style={style}
      role="dialog"
      aria-label={t('Consulta de palabra')}
    >
      <div className="youjp-inspector-head" onMouseDown={empezar}>
        <span className="youjp-inspector-mark" aria-hidden="true">辞</span>
        <span className="youjp-inspector-title">{t('Diccionario')}</span>
        {actual && (
          <button type="button" className="youjp-transcript-action"
            onMouseDown={(event) => event.stopPropagation()}
            onClick={onResetPosition} title={t('Devolver la consulta a su sitio')}
            aria-label={t('Restablecer posición de la consulta')}
          >⌖</button>
        )}
        <button type="button" className="youjp-transcript-action"
          onMouseDown={(event) => event.stopPropagation()}
          onClick={onClose} aria-label={t('Cerrar consulta')}
        >×</button>
      </div>
      <WordCard language={language} token={token} target={target} onClose={onClose} showClose={false} />
    </div>
  );
}
