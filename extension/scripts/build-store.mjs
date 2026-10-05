// Paquete para Chrome Web Store y Edge Add-ons: sin `key` en el manifest (la
// tienda asigna su propio ID). Sale en .output-store/, sin tocar el build con
// clave de .output/. Uso: npm run zip:store
import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const wxt = fileURLToPath(new URL('../node_modules/wxt/bin/wxt.mjs', import.meta.url));
const run = (browser) =>
  spawnSync(process.execPath, [wxt, 'zip', '-b', browser], {
    cwd: root,
    stdio: 'inherit',
    env: { ...process.env, YOUJP_STORE_BUILD: '1' },
  });

// El manifest MV3 es el mismo para ambos navegadores: se empaqueta una vez por
// cada uno para que el nombre del zip indique a cuál se sube.
for (const browser of ['chrome', 'edge']) {
  const result = run(browser);
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
const out = new URL('../.output-store/', import.meta.url);
for (const name of readdirSync(out).filter((n) => n.endsWith('.zip'))) {
  console.log(`Listo: extension/.output-store/${name}`);
}
