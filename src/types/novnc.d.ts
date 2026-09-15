/* Minimal ambient types for the bundled noVNC client (MPL-2.0).
   Only the surface Vortex Terminal uses is declared; noVNC ships no .d.ts. */
declare module '@novnc/novnc' {
  export interface RFBCredentials {
    username?: string;
    password?: string;
    target?: string;
  }

  export interface RFBOptions {
    credentials?: RFBCredentials;
    shared?: boolean;
    repeaterID?: string;
    wsProtocols?: string[];
  }

  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, urlOrChannel?: string | WebSocket, options?: RFBOptions);
    disconnect(): void;
    sendCredentials(credentials: RFBCredentials): void;
    sendCtrlAltDel(): void;
    focus(): void;
    blur(): void;
    /** Present in noVNC, but never called by Vortex: clipboard stays opt-out. */
    clipboardPasteFrom(text: string): void;
    readonly connected: boolean;
    readonly name: string;
    background: string;
    scaleViewport: boolean;
    clipViewport: boolean;
    resizeSession: boolean;
    viewOnly: boolean;
    showDotCursor: boolean;
  }
}
