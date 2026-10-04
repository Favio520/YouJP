/**
 * Iconos de YouJP.
 *
 * Un lenguaje propio y pequeño: trazo redondeado de 1,7 y una pieza rellena
 * en tono suave que marca "dónde está la acción" (la perilla del ajuste, el
 * rollo del pergamino, la banda del subtítulo). Es el mismo dibujo en los
 * paneles (React) y en los botones de la barra de YouTube (DOM), por eso las
 * formas son datos y no JSX.
 */

export type IconName = 'history' | 'settings' | 'move' | 'close' | 'reset' | 'translate';

export interface IconShape {
  tag: 'path' | 'circle' | 'rect';
  attrs: Record<string, string | number>;
  /** soft: relleno tenue con trazo · tint: relleno tenue sin trazo · solid: lleno. */
  tone?: 'soft' | 'tint' | 'solid';
  /** Solo DOM: gira sin parar (progreso indeterminado). */
  spin?: boolean;
}

const grip = (cx: number, cy: number): IconShape =>
  ({ tag: 'circle', attrs: { cx, cy, r: 1.5 }, tone: 'solid' });

export const ICONS: Record<IconName, IconShape[]> = {
  // Tres correderas con perilla: cada una a una altura distinta.
  settings: [
    { tag: 'path', attrs: { d: 'M4 6h8.8M17.2 6H20M4 12h1.8M10.2 12H20M4 18h10.8M19.2 18H20' } },
    { tag: 'circle', attrs: { cx: 15, cy: 6, r: 2.2 }, tone: 'soft' },
    { tag: 'circle', attrs: { cx: 8, cy: 12, r: 2.2 }, tone: 'soft' },
    { tag: 'circle', attrs: { cx: 17, cy: 18, r: 2.2 }, tone: 'soft' },
  ],
  // Un pergamino: la hoja con renglones y el rollo a un lado.
  history: [
    { tag: 'rect', attrs: { x: 6.5, y: 4.5, width: 13, height: 15, rx: 2.2 } },
    { tag: 'path', attrs: { d: 'M10.5 9.5h5M10.5 12.5h5M10.5 15.5h3' } },
    { tag: 'rect', attrs: { x: 3.5, y: 3.5, width: 4, height: 17, rx: 2 }, tone: 'soft' },
  ],
  // Pantalla con la banda del subtítulo: el japonés arriba, la traducción debajo.
  translate: [
    { tag: 'rect', attrs: { x: 3, y: 5, width: 18, height: 14, rx: 3.5 } },
    { tag: 'rect', attrs: { x: 3.9, y: 11.6, width: 16.2, height: 6.5, rx: 2.4 }, tone: 'tint' },
    { tag: 'path', attrs: { d: 'M7.5 8.6h6M7.5 14.8h9' } },
  ],
  move: [grip(9, 6), grip(15, 6), grip(9, 12), grip(15, 12), grip(9, 18), grip(15, 18)],
  close: [{ tag: 'path', attrs: { d: 'm6 6 12 12M18 6 6 18' } }],
  reset: [{ tag: 'path', attrs: { d: 'M4 10a8 8 0 1 1 2 8M4 4v6h6' } }],
};

/** Atributos de presentación que cada forma añade según su tono. */
export function toneAttributes(tone: IconShape['tone']): Record<string, string | number> {
  if (tone === 'soft') return { fill: 'currentColor', fillOpacity: 0.28 };
  if (tone === 'tint') return { fill: 'currentColor', fillOpacity: 0.28, stroke: 'none' };
  if (tone === 'solid') return { fill: 'currentColor', stroke: 'none' };
  return {};
}

/** Forma con sus atributos finales, en camelCase (lo que espera React). */
export const shapeAttributes = (shape: IconShape): Record<string, string | number> =>
  ({ ...toneAttributes(shape.tone), ...shape.attrs });

const DOM_NAMES: Record<string, string> = {
  fillOpacity: 'fill-opacity', strokeWidth: 'stroke-width', strokeDasharray: 'stroke-dasharray',
};

const SVG_NS = 'http://www.w3.org/2000/svg';

/** Dibuja formas en un `<svg>` del DOM. Lo usan los botones de la barra de YouTube. */
export function buildSvg(shapes: IconShape[], size = 22): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, 'svg');
  const attributes: Record<string, string> = {
    viewBox: '0 0 24 24', width: String(size), height: String(size), fill: 'none',
    stroke: 'currentColor', 'stroke-width': '1.7', 'stroke-linecap': 'round',
    'stroke-linejoin': 'round', 'aria-hidden': 'true',
  };
  for (const [name, value] of Object.entries(attributes)) svg.setAttribute(name, value);
  for (const shape of shapes) {
    const element = document.createElementNS(SVG_NS, shape.tag);
    for (const [name, value] of Object.entries(shapeAttributes(shape))) {
      element.setAttribute(DOM_NAMES[name] ?? name, String(value));
    }
    if (shape.spin) {
      const spin = document.createElementNS(SVG_NS, 'animateTransform');
      spin.setAttribute('attributeName', 'transform');
      spin.setAttribute('type', 'rotate');
      spin.setAttribute('from', '0 12 12');
      spin.setAttribute('to', '360 12 12');
      spin.setAttribute('dur', '1.1s');
      spin.setAttribute('repeatCount', 'indefinite');
      element.append(spin);
    }
    svg.append(element);
  }
  return svg;
}
