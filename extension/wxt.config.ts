import { defineConfig } from 'wxt';

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  // El build de tienda no lleva `key`: va a otra carpeta para no pisar el build
  // con clave que usa el paquete de Windows.
  outDir: process.env.YOUJP_STORE_BUILD ? '.output-store' : '.output',
  manifest: {
    // Clave pública de desarrollo: conserva el mismo ID al reconstruir la extensión.
    // Las tiendas asignan su propio ID y no aceptan este campo: YOUJP_STORE_BUILD=1
    // lo omite, y el ID de la tienda se añade a YOUJP_ALLOWED_EXTENSION_IDS.
    key: process.env.YOUJP_STORE_BUILD ? undefined : 'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvGLB8JzzzwlvtVygDzRgukCvhm9ScEurTbTIV3pYmHVwp7Wj52YUxkf7w/9G8ZIJmVzIG1AU5FSwYQN2F0ffNz36oQzUdwqA6RpljqHvK4k3Y6TcVxn2ps5uLUSlneO8XuyebDMAW8zY+i/EwQZXWFehPs+EQZyxJUL1QH8FC6qdL+VVNQRzly9qDHp0mwUvlAl5kA8Lq+y/cDsBd5qCBlrDeJWE6HJdv3u73nDUEtGDoPOGrSATqBo51jSgM2nO17sFawNUcN3XK9B+J+QZQNIHXXGofPtP0tTOD3wMNqdaMEHgLFn83zju0thlX/0EyiglOm3TJ74qjRcTsAUA9QIDAQAB',
    name: 'youjp — subtítulos japoneses',
    description:
      'Captura el audio de una pestaña de YouTube y muestra subtítulos japoneses en tiempo real.',
    permissions: [
      // getMediaStreamId(). Solo se puede invocar tras un gesto del usuario.
      'tabCapture',
      // El documento offscreen es quien sostiene el audio y el WebSocket: el
      // service worker se termina por inactividad y se llevaria la sesion.
      'offscreen',
      // Para reinyectar el content script en pestañas que ya estaban abiertas
      // cuando se recargó la extensión. Sin esto, todo funciona menos la parte
      // que se ve.
      'scripting',
      'storage',
      // El atajo de captura concede acceso temporal a la pestaña visible.
      'activeTab',
    ],
    host_permissions: [
      'https://www.youtube.com/*',
      'http://127.0.0.1/*',
      'http://localhost/*',
    ],
    action: {
      // Sin default_popup a proposito: con popup, action.onClicked no se
      // dispara, y ese clic es el gesto de usuario que habilita tabCapture.
      default_title: 'YouJP: subtítulos en YouTube · recorte en otras páginas',
      // Chrome usaría el bloque `icons` como respaldo, pero declararlo aquí
      // evita depender de ese comportamiento implícito.
      default_icon: {
        16: 'icon/16.png',
        32: 'icon/32.png',
        48: 'icon/48.png',
        128: 'icon/128.png',
      },
    },
    commands: {
      'translate-selection': {
        suggested_key: { default: 'Alt+Shift+S' },
        description: 'Seleccionar una zona de la pestaña para traducir japonés',
      },
    },
  },
  webExt: {
    // Abre directamente en YouTube al lanzar `npm run dev`.
    startUrls: ['https://www.youtube.com/'],
  },
});
