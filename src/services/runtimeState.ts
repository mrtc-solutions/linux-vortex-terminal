/* Tiny shared runtime flag. Kept dependency-free so vortexApi,
 * webConversations and runtime detection can all read it without
 * circular imports. Set exclusively by services/runtime.ts. */

export type VortexRuntime = 'LOCAL_LINUX' | 'WEB_CLOUD' | 'UNKNOWN';

let current: VortexRuntime = 'UNKNOWN';

export function setCurrentRuntime(runtime: VortexRuntime): void {
  current = runtime;
}

export function currentRuntime(): VortexRuntime {
  return current;
}

export function isWeb(): boolean {
  return current === 'WEB_CLOUD';
}
