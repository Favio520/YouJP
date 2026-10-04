/** Isolated UI review. Uses production components; no backend or capture. */
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Overlay } from '../src/ui/Overlay';
import { DEFAULT_SETTINGS } from '../src/settings';
import type { ExtensionMessage } from '../src/messages';
import '../src/ui/overlay.css';
import './preview.css';

const listeners = new Set<(message: ExtensionMessage) => void>();
let stored = { ...DEFAULT_SETTINGS, history: 0 };
Object.defineProperty(globalThis, 'chrome', { value: {
  runtime: { onMessage: { addListener: (fn: (message: ExtensionMessage) => void) => listeners.add(fn),
    removeListener: (fn: (message: ExtensionMessage) => void) => listeners.delete(fn) } },
  storage: { local: { get: async () => ({ overlaySettings: stored }),
    set: async (value: { overlaySettings: typeof stored }) => { stored = value.overlaySettings; } },
    onChanged: { addListener() {}, removeListener() {} } },
}, configurable: true });

const entry = { id: 1, headword: '景色', readings: ['けしき'], common: true, freq_rank: 1,
  senses: [{ pos: ['n'], glosses_es: ['paisaje', 'vista', 'escenario'], glosses_en: ['scenery', 'view', 'landscape'] }] };
const token = { i: 0, span: [0, 2], surface: '景色', lemma: '景色', kana: 'けしき', romaji: 'keshiki',
  pos: ['名詞'], pos_label: 'sustantivo', chain: [], clickable: true, entry };
const phrases = [
  ['今日はいい天気ですね。', 'Hoy hace buen tiempo, ¿verdad?'],
  ['少し歩いてみましょう。', 'Vamos a caminar un poco.'],
  ['桜が咲いています。', 'Los cerezos están en flor.'],
  ['この景色を忘れたくない。', 'No quiero olvidar este paisaje.'],
  ['景色がとても綺麗ですね。', 'El paisaje es muy bonito, ¿verdad?'],
];
function emit(message: unknown) { for (const listener of listeners) listener(message as ExtensionMessage); }
function populate() {
  emit({ type: 'status', status: 'starting' });
  emit({ type: 'status', status: 'running' });
  phrases.forEach(([text,translation],i) => {
    emit({ type: 'subtitle.final', payload: { segment_id:i+1, text, media_start_ms:(i+1)*15000 } });
    emit({ type: 'subtitle.translation', payload: { segment_id:i+1, text:translation, target:'es' } });
    if(i===4) emit({ type:'subtitle.tokens', payload:{ segment_id:5, tokens:[token,
      { ...token, i:1, surface:'がとても綺麗ですね。', kana:'', entry:null, clickable:false }] } });
  });
}

function Preview() {
  const [size,setSize] = useState('wide');
  useEffect(() => { const timer = setTimeout(populate, 150); return () => clearTimeout(timer); }, []);
  return <main className="preview">
    <header className="preview-head"><div><span className="preview-kicker">YOUJP / STUDIO</span><h1>El japonés, frase a frase.</h1>
      <p>Vista interactiva de los componentes reales de la extensión.</p></div>
      <span className="preview-badge">UI REVIEW · SIN CAPTURA</span></header>
    <nav className="preview-controls" aria-label="Escenarios de revisión">
      <button type="button" onClick={populate}>Sesión activa</button>
      <button type="button" onClick={() => emit({ type:'status', status:'starting' })}>Iniciando</button>
      <button type="button" onClick={() => emit({ type:'status', status:'error', detail:'No se pudo conectar. Vuelve a iniciar YouJP.' })}>Error</button>
      <button type="button" onClick={() => { emit({ type:'status', status:'idle' }); window.dispatchEvent(new KeyboardEvent('keydown',{ altKey:true,code:'KeyH' })); }}>Historial vacío</button>
      <button type="button" onClick={() => window.dispatchEvent(new KeyboardEvent('keydown',{ altKey:true,code:'KeyH' }))}>Historial</button>
      <button type="button" onClick={() => window.dispatchEvent(new Event('youjp:toggle-settings'))}>Ajustes</button>
      <button type="button" aria-pressed={size==='compact'} onClick={() => setSize(size==='wide'?'compact':'wide')}>Reproductor compacto</button>
    </nav>
    <div className={`preview-player preview-player--${size}`} id="movie_player">
      <div className="preview-landscape" /><div className="preview-video-title"><small>日本を歩く</small><span>Un paseo por Japón</span></div>
      <div className="youjp-theme"><Overlay /></div>
      <div className="preview-video-controls"><span>Ⅱ</span><span>1:15 / 8:42</span><div className="preview-track"><i /></div><span>HD</span></div>
    </div>
    <footer className="preview-footer"><span>Pulsa <b>景色</b> para consultar su significado. Los paneles se pueden mover y redimensionar.</span>
      <span><kbd>Alt + H</kbd> historial · <kbd>Alt + S</kbd> ajustes · <kbd>Esc</kbd> cerrar</span></footer>
  </main>;
}
const mount = document.getElementById('app');
if (mount) createRoot(mount).render(<Preview />);
