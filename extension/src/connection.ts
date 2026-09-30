import {
  PROTOCOL_VERSION, SAMPLE_RATE, FRAME_MS,
  type ClientMessage, type ServerMessage, type SessionReady, type SessionStart,
} from './protocol';

interface Options {
  url: string;
  handshake: () => SessionStart;
  onReady: (message: SessionReady) => void;
  onMessage: (message: ServerMessage) => void;
  onRetry: (attempt: number, delayMs: number) => void;
  onFatal: (detail: string) => void;
}

/** Mantiene un solo socket y sus temporizadores. El audio no se reenvía. */
export class ReconnectingSession {
  private socket: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private heartbeat: ReturnType<typeof setTimeout> | undefined;
  private stopped = false;
  private ready = false;
  private attempts = 0;
  private lastSeen = 0;

  constructor(private readonly options: Options) {}

  start(): void {
    if (this.socket || this.timer !== undefined || this.stopped) return;
    this.connect();
  }

  private clearTimers(): void {
    clearTimeout(this.timer);
    clearTimeout(this.heartbeat);
    this.timer = undefined;
    this.heartbeat = undefined;
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    if (this.ready) this.send({ type: 'session.stop' });
    this.ready = false;
    const ws = this.socket;
    this.socket = null;
    ws?.close();
  }

  send(message: ClientMessage | ArrayBuffer): boolean {
    if (!this.ready || this.socket?.readyState !== WebSocket.OPEN) return false;
    if (message instanceof ArrayBuffer && this.socket.bufferedAmount > 64_000) return false;
    try {
      this.socket.send(message instanceof ArrayBuffer ? message : JSON.stringify(message));
      return true;
    } catch {
      this.retry();
      return false;
    }
  }

  private fatal(detail: string): void {
    this.stop();
    this.options.onFatal(detail);
  }

  private retry(): void {
    if (this.stopped) return;
    this.clearTimers();
    this.ready = false;
    const old = this.socket;
    this.socket = null;
    old?.close();
    // Reintenta mientras siga la captura; stop cancela de inmediato.
    const delay = Math.min(1000 * 2 ** Math.min(this.attempts++, 5), 30_000);
    this.options.onRetry(this.attempts, delay);
    if (this.stopped) return;
    this.timer = setTimeout(() => this.connect(), delay);
  }

  private pulse(): void {
    this.heartbeat = setTimeout(() => {
      if (this.stopped || !this.ready) return;
      if (Date.now() - this.lastSeen >= 15_000) {
        this.retry();
        return;
      }
      if (this.send({ type: 'ping', t: Date.now() })) this.pulse();
    }, 5000);
  }

  private connect(): void {
    if (this.stopped) return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.options.url);
    } catch (error) {
      this.fatal(`Dirección del backend no válida: ${String(error)}`);
      return;
    }
    this.socket = ws;
    ws.binaryType = 'arraybuffer';
    const active = () => !this.stopped && this.socket === ws;
    // El plazo incluye session.ready, además de la apertura del socket.
    this.timer = setTimeout(() => { if (active()) this.retry(); }, 10_000);
    ws.addEventListener('open', () => {
      if (!active()) return;
      try { ws.send(JSON.stringify(this.options.handshake())); }
      catch { this.retry(); }
    });
    ws.addEventListener('error', () => { if (active()) this.retry(); });
    ws.addEventListener('close', (event) => {
      if (!active()) return;
      if (event.code === 1002) {
        this.fatal('El backend rechazó la sesión. Actualiza YouJP y recarga la extensión.');
      } else if (event.code === 1008) {
        // Origen no permitido: no es cuestión de versiones sino del ID de la extensión.
        this.fatal(`El backend no reconoce esta extensión (ID ${chrome.runtime.id}). ` +
          'Carga la versión compilada de YouJP o añade este ID a YOUJP_ALLOWED_EXTENSION_IDS.');
      } else this.retry();
    });
    ws.addEventListener('message', (event) => {
      if (!active() || typeof event.data !== 'string') return;
      let message: ServerMessage;
      try { message = JSON.parse(event.data) as ServerMessage; }
      catch { return; }
      if (!message || typeof message.type !== 'string') return;
      this.lastSeen = Date.now();
      if (message.type === 'error' && message.fatal) {
        this.fatal(message.message);
        return;
      }
      if (message.type === 'session.ready') {
        if (this.ready) return;
        if (message.protocol_version !== PROTOCOL_VERSION || message.sample_rate !== SAMPLE_RATE ||
            message.frame_ms !== FRAME_MS || typeof message.session_id !== 'string') {
          this.fatal('Backend y extensión incompatibles. Actualiza ambos y recarga la extensión.');
          return;
        }
        clearTimeout(this.timer);
        this.ready = true;
        this.attempts = 0;
        this.options.onReady(message);
        if (active() && this.ready) this.pulse();
      } else if (this.ready) this.options.onMessage(message);
    });
  }
}
