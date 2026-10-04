import { ICONS, shapeAttributes, type IconName } from './iconShapes';

/** Iconos propios de YouJP (ver `iconShapes.ts`). Sin fuentes ni red. */
export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {ICONS[name].map((shape) => {
        const props = shapeAttributes(shape);
        const key = JSON.stringify(shape.attrs);
        if (shape.tag === 'path') return <path key={key} {...props} />;
        if (shape.tag === 'circle') return <circle key={key} {...props} />;
        return <rect key={key} {...props} />;
      })}
    </svg>
  );
}
