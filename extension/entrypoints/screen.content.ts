import { defineContentScript } from '#imports';
import { configureScreenTranslator, disposeScreenTranslator, onScreenCaptureProgress, startScreenSelection } from '@/src/ui/ScreenTranslator';
import { loadSettings, onSettingsChanged } from '@/src/settings';

// Injected only after the user invokes the shortcut or toolbar action.
export default defineContentScript({
  registration: 'runtime',
  main(ctx) {
    let active = true;
    let changed = false;
    const stopSettings = onSettingsChanged((settings) => { changed = true; configureScreenTranslator(settings); });
    void loadSettings().then((initial) => { if (active && !changed) configureScreenTranslator(initial); });
    const onMessage = (message: unknown, sender: chrome.runtime.MessageSender,
      respond: (response?: unknown) => void) => {
      if (sender.id !== chrome.runtime.id || !message || typeof message !== 'object' ||
          !('type' in message)) return;
      if (message.type === 'screen.probe') respond({ ready: true });
      if (message.type === 'screen.select') startScreenSelection();
      if (message.type === 'screen.capture.progress') {
        onScreenCaptureProgress('requestId' in message && typeof message.requestId === 'number' ? message.requestId : undefined);
      }
    };
    chrome.runtime.onMessage.addListener(onMessage);
    ctx.addEventListener(window, 'pagehide', disposeScreenTranslator);
    ctx.addEventListener(window, 'popstate', disposeScreenTranslator);
    ctx.addEventListener(window, 'hashchange', disposeScreenTranslator);
    ctx.addEventListener(window, 'wxt:locationchange', disposeScreenTranslator);
    ctx.onInvalidated(() => {
      active = false;
      stopSettings();
      chrome.runtime.onMessage.removeListener(onMessage);
      disposeScreenTranslator();
    });
  },
});
