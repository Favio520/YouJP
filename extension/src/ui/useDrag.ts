/**
 * Arrastre del overlay dentro del reproductor.
 *
 * La posición se guarda en porcentaje del reproductor y no en píxeles: así
 * sobrevive al cambio a pantalla completa, al modo teatro y al redimensionado
 * de la ventana, que es exactamente cuando un overlay colocado a mano se
 * descoloca y hay que volver a ponerlo.
 *
 * Se arrastra desde un asa y no desde el propio subtítulo, porque el subtítulo
 * está lleno de palabras pulsables y un arrastre accidental abriría tarjetas al
 * azar.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { findPlayerRoot } from '../player';

export interface Position {
  x: number;
  y: number;
}

/** Margen mínimo al borde, en porcentaje, para que nunca quede inalcanzable. */
const MARGEN = 3;

const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

export function useDrag(onCommit: (position: Position) => void) {
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<Position | null>(null);
  const estado = useRef<{ rect: DOMRect } | null>(null);

  const mover = useCallback((event: MouseEvent) => {
    const rect = estado.current?.rect;
    if (!rect || rect.width === 0 || rect.height === 0) return;
    setPreview({
      x: clamp(((event.clientX - rect.left) / rect.width) * 100, MARGEN, 100 - MARGEN),
      y: clamp(((event.clientY - rect.top) / rect.height) * 100, MARGEN, 100 - MARGEN),
    });
  }, []);

  const soltar = useCallback(() => {
    setDragging(false);
    estado.current = null;
    setPreview((actual) => {
      if (actual) onCommit(actual);
      return null;
    });
  }, [onCommit]);

  useEffect(() => {
    if (!dragging) return;
    // En `capture` y sobre `window`: el reproductor de YouTube captura eventos
    // de ratón para sus propios controles, y sin esto el arrastre se pierde en
    // cuanto el cursor pasa por encima de la barra.
    window.addEventListener('mousemove', mover, true);
    window.addEventListener('mouseup', soltar, true);
    return () => {
      window.removeEventListener('mousemove', mover, true);
      window.removeEventListener('mouseup', soltar, true);
    };
  }, [dragging, mover, soltar]);

  const empezar = useCallback((event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    const player = findPlayerRoot();
    if (!player) return;
    estado.current = { rect: player.getBoundingClientRect() };
    setDragging(true);
  }, []);

  return { dragging, preview, empezar };
}
