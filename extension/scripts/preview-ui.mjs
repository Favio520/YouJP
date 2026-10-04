import { context } from 'esbuild';
import { createServer } from 'node:http';
import { readFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const root = fileURLToPath(new URL('..', import.meta.url));
const output = resolve(root, '../.youjp/ui-preview');
mkdirSync(output,{recursive:true});
const build = await context({ entryPoints:[resolve(root,'dev-ui/preview.tsx')], bundle:true,
  outfile:resolve(output,'app.js'), platform:'browser', format:'esm', jsx:'automatic', sourcemap:true,
  external:['/landscape.png'] });
await build.rebuild();
await build.watch();
const files = {
  '/':[resolve(root,'dev-ui/index.html'),'text/html'],
  '/app.js':[resolve(output,'app.js'),'text/javascript'],
  '/app.css':[resolve(output,'app.css'),'text/css'],
  '/app.js.map':[resolve(output,'app.js.map'),'application/json'],
  '/app.css.map':[resolve(output,'app.css.map'),'application/json'],
  '/landscape.png':[resolve(root,'../scripts/windows/assets/fuji-pastel.png'),'image/png'],
};
const server=createServer((req,res) => {
  const file=files[new URL(req.url,'http://127.0.0.1').pathname];
  if(!file) {res.writeHead(404);res.end();return;}
  try {res.writeHead(200,{'Content-Type':file[1],'Cache-Control':'no-store'});res.end(readFileSync(file[0]));}
  catch {res.writeHead(500);res.end('Preview asset unavailable');}
});
server.listen(4178,'127.0.0.1',() => process.stdout.write('YouJP UI preview: http://127.0.0.1:4178\n'));
process.on('SIGINT',async() => {server.close();await build.dispose();process.exit();});
