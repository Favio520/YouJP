import { defineConfig } from 'wxt';

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  manifest: {
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
    ],
    host_permissions: ['https://www.youtube.com/*'],
    action: {
      // Sin default_popup a proposito: con popup, action.onClicked no se
      // dispara, y ese clic es el gesto de usuario que habilita tabCapture.
      default_title: 'Activar subtítulos japoneses',
    },
  },
  webExt: {
    // Abre directamente en YouTube al lanzar `npm run dev`.
    startUrls: ['https://www.youtube.com/'],
  },
});
