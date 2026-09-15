import { useEffect, useRef, useState } from 'react';
import {
  JsonRecord, activateGguf, importGguf, localFilePath, pullOllamaModel,
  activateOllamaModel, removeOllamaModel, startOllamaServer, stopOllamaServer,
  installOllama, cancelOllamaInstall, cancelOllamaPull,
} from '../../services/vortexApi';
import { ErrorLine, GhostButton, PrimaryButton, Section, asRecord, inputCls } from './common';

const roles = ['primary', 'planner', 'fast', 'specialist'];
export function ModelManagement({ gguf, runtime, catalog, refresh, onOpenPopup }: {
  gguf: JsonRecord | null; runtime: JsonRecord | null; catalog: JsonRecord;
  refresh: () => Promise<void>; onOpenPopup: (kind: string, props?: JsonRecord) => void;
}) {
  const [role, setRole] = useState('primary');
  const [path, setPath] = useState('');
  const [modelName, setModelName] = useState('');
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [confirmation, setConfirmation] = useState<{ label: string; action: () => Promise<unknown> } | null>(null);
  const run = async (action: () => Promise<unknown>) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await action();
      await refresh();
      setNotice('Request completed. Provider status refreshed.');
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { lock.current = false; setBusy(false); }
  };
  const confirm = (label: string, action: () => Promise<unknown>) => setConfirmation({ label, action });
  const items = [...(Array.isArray(catalog.items) ? catalog.items : []), ...(Array.isArray(catalog.extras) ? catalog.extras : [])].map(asRecord);
  const downloads = asRecord(catalog.downloads);
  const install = asRecord(runtime?.install);
  const activeStates = ['queued', 'starting', 'started', 'running', 'downloading', 'pulling'];
  const active = activeStates.includes(String(install.status)) || Object.values(downloads).some(job => activeStates.includes(String(asRecord(job).status)));
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => { if (!lock.current) void refresh(); }, 3000);
    return () => window.clearInterval(timer);
  }, [active, refresh]);
  const installRuntime = async () => {
    const result = await installOllama();
    if (result.planned && asRecord(result.plan).id) {
      onOpenPopup('approvals', { plan: result.plan, guardian: result.guardian });
    } else if (asRecord(result.install).error) {
      throw new Error(String(asRecord(result.install).error));
    }
  };
  return <div className="space-y-4">
    <ErrorLine message={error} />
    {notice && <p role="status">{notice}</p>}
    <label className="block">Advisory model role
      <select aria-label="Advisory model role" value={role} onChange={e => setRole(e.target.value)} className={inputCls}>
        {roles.map(r => <option key={r} value={r}>{r}</option>)}
      </select>
    </label>
    {confirmation && <div role="group" aria-label="Confirm model change" className="p-3 border border-amber-700 space-y-2">
      <p>{confirmation.label}</p>
      <p>Downloads use network and disk space. Removal deletes the selected local model. No change until confirmed.</p>
      <PrimaryButton disabled={busy} onClick={() => { const action = confirmation.action; setConfirmation(null); void run(action); }}>Confirm model change</PrimaryButton>
      <GhostButton disabled={busy} onClick={() => setConfirmation(null)}>Cancel model change</GhostButton>
    </div>}
    <Section title="Import and activate GGUF">
      <p>Enter a file path on the sidecar host, or select a local file in the desktop app. A browser file is not uploaded.</p>
      <input aria-label="GGUF path on sidecar host" value={path} onChange={e => setPath(e.target.value)} className={inputCls} placeholder="/path/to/model.gguf" />
      <PrimaryButton disabled={busy || !path.trim()} onClick={() => void run(() => importGguf(path.trim()))}>Import GGUF path</PrimaryButton>
      <input type="file" accept=".gguf" aria-label="Select desktop GGUF file" disabled={busy} onChange={e => {
        const file = e.target.files?.[0]; e.target.value = '';
        if (!file) return;
        const selected = localFilePath(file);
        if (!selected) { setError('File selection requires the desktop app. In a browser, enter a path on the sidecar host.'); return; }
        setPath(selected); void run(() => importGguf(selected));
      }} />
      {(Array.isArray(gguf?.files) ? gguf.files : []).map(asRecord).map(file => <div key={String(file.name)} className="flex flex-wrap gap-2 items-center py-1">
        <span>{String(file.name)}</span>
        <GhostButton disabled={busy} onClick={() => void run(() => activateGguf(String(file.name), role))}>Use {String(file.name)} for {role}</GhostButton>
      </div>)}
    </Section>
    <Section title="Manage Ollama">
      <p>API: {String(runtime?.api_state || 'unavailable')} · {String(runtime?.api_reason || '')}</p>
      <div className="flex flex-wrap gap-2">
        {!runtime?.installed && <PrimaryButton disabled={busy} onClick={() => confirm('Install the official Ollama runtime?', installRuntime)}>Install Ollama</PrimaryButton>}
        {activeStates.includes(String(install.status)) && <GhostButton disabled={busy} onClick={() => void run(cancelOllamaInstall)}>Cancel Ollama install</GhostButton>}
        <GhostButton disabled={busy || !runtime?.installed} onClick={() => void run(startOllamaServer)}>Start Ollama server</GhostButton>
        <GhostButton disabled={busy} onClick={() => confirm('Stop the managed Ollama server?', stopOllamaServer)}>Stop Ollama server</GhostButton>
      </div>
      <p role="status">Runtime install: {String(install.status || 'idle')} {String(install.error || '')}</p>
      <input aria-label="Ollama model name" placeholder="llama3.2:3b" value={modelName} onChange={e => setModelName(e.target.value)} className={inputCls} />
      <PrimaryButton disabled={busy || !modelName.trim()} onClick={() => { const name = modelName.trim(); const selectedRole = role; confirm(`Download ${name} for ${selectedRole}?`, () => pullOllamaModel(name, selectedRole)); }}>Download named model</PrimaryButton>
      {items.map(item => {
        const name = String(item.installed_name || item.name);
        const job = asRecord(downloads[String(item.name)] || item.download);
        return <div key={String(item.name)} className="p-2 border-b border-[var(--theme-border)] space-y-1">
          <p>{String(item.label || name)} · {item.installed ? 'installed' : 'not installed'} {item.approx_size_gb ? `· approximately ${item.approx_size_gb} GiB` : ''}</p>
          <p>{String(job.status || '')} {String(job.error || '')}</p>
          <div className="flex flex-wrap gap-2">
            {item.installed ? <>
              <GhostButton disabled={busy} onClick={() => void run(() => activateOllamaModel(name, role))}>Use {name} for {role}</GhostButton>
              <GhostButton disabled={busy} onClick={() => confirm(`Remove local model ${name}?`, () => removeOllamaModel(name))}>Remove {name}</GhostButton>
            </> : <GhostButton disabled={busy} onClick={() => { const selectedRole = role; confirm(`Download ${name}?`, () => pullOllamaModel(name, selectedRole)); }}>Download {name}</GhostButton>}
            {activeStates.includes(String(job.status)) && <GhostButton disabled={busy} onClick={() => void run(() => cancelOllamaPull(String(item.name)))}>Cancel download {name}</GhostButton>}
          </div>
        </div>;
      })}
    </Section>
  </div>;
}
