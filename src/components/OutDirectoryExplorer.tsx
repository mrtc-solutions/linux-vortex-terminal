import React, { useState, useEffect } from 'react';
import { vfs } from '../services/virtualFileSystem';
import { OutFileArtifact } from '../types/terminal';
import { 
  FolderDown, 
  FileText, 
  Download, 
  Trash2, 
  Eye, 
  Search, 
  FileCode, 
  RefreshCw, 
  Check, 
  Binary, 
  Share2,
  Plus
} from 'lucide-react';
import { sound } from '../services/soundEffects';

interface OutDirectoryExplorerProps {
  onArtifactChange?: () => void;
  onRunTerminalCommand?: (cmd: string) => void;
}

export const OutDirectoryExplorer: React.FC<OutDirectoryExplorerProps> = ({
  onArtifactChange,
  onRunTerminalCommand,
}) => {
  const [artifacts, setArtifacts] = useState<OutFileArtifact[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<OutFileArtifact | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [viewHex, setViewHex] = useState(false);
  const [isCopied, setIsCopied] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newFilePath, setNewFilePath] = useState('/out/scans/custom-target.txt');
  const [newFileContent, setNewFileContent] = useState('Target: 192.168.1.100\nStatus: Pending Audit\nNotes: AI synthesized artifact');

  const reload = () => {
    const list = vfs.getAllOutArtifacts();
    setArtifacts(list);
    if (selectedArtifact) {
      const updated = list.find((a) => a.path === selectedArtifact.path);
      setSelectedArtifact(updated || null);
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const filtered = artifacts.filter((a) => {
    const matchSearch =
      a.filename.toLowerCase().includes(searchQuery.toLowerCase()) ||
      a.path.toLowerCase().includes(searchQuery.toLowerCase()) ||
      a.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchCategory = selectedCategory === 'all' || a.category === selectedCategory;
    return matchSearch && matchCategory;
  });

  const categories = ['all', 'reports', 'scans', 'captures', 'creds', 'payloads', 'logs'];

  const handleDownload = (artifact: OutFileArtifact) => {
    sound.playExecute();
    const blob = new Blob([artifact.content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = artifact.filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleExportAll = () => {
    sound.playSuccess();
    const archiveData = {
      project: "NEO-HEX Out Directory Workspace",
      exportedAt: new Date().toISOString(),
      totalArtifacts: artifacts.length,
      files: artifacts.map((a) => ({
        path: a.path,
        filename: a.filename,
        category: a.category,
        size: a.size,
        createdAt: a.createdAt,
        content: a.content,
      })),
    };
    const blob = new Blob([JSON.stringify(archiveData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `neohex-out-workspace-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleDelete = (path: string) => {
    sound.playAlert();
    vfs.deleteArtifact(path);
    reload();
    if (onArtifactChange) onArtifactChange();
    if (selectedArtifact?.path === path) setSelectedArtifact(null);
  };

  const handleCreateFile = () => {
    if (!newFilePath) return;
    vfs.writeFile(newFilePath, newFileContent, 'scans', 'User-created artifact');
    setShowCreateModal(false);
    reload();
    if (onArtifactChange) onArtifactChange();
    sound.playSuccess();
  };

  // Convert string to hex representation
  const toHexDump = (str: string) => {
    const lines = [];
    for (let i = 0; i < Math.min(str.length, 512); i += 16) {
      const slice = str.slice(i, i + 16);
      const hex = Array.from(slice)
        .map((c) => c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join(' ');
      const ascii = slice.replace(/[^\x20-\x7E]/g, '.');
      lines.push(`${i.toString(16).padStart(4, '0')}  ${hex.padEnd(48, ' ')}  |${ascii}|`);
    }
    return lines.join('\n');
  };

  const totalBytes = artifacts.reduce((acc, a) => acc + (a.size || 0), 0);

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--theme-bg)] font-mono text-xs overflow-hidden select-text">
      {/* Top Banner / Out directory stats */}
      <div className="bg-[var(--theme-surface)]/90 border-b border-[var(--theme-border)] px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-3">
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] text-[var(--theme-primary)]">
            <FolderDown className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-sm font-bold text-[var(--theme-primary)] glow-primary">
                /out VIRTUAL ARTIFACTS REPOSITORY
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                ACTIVE WRITETHROUGH
              </span>
            </div>
            <div className="text-[11px] text-stone-400 mt-0.5">
              Tracks all outputs, scan results, pcap dumps, and auto-generated security reports ({artifacts.length} files &middot; {(totalBytes / 1024).toFixed(1)} KB)
            </div>
          </div>
        </div>

        {/* Global Out Actions */}
        <div className="flex items-center space-x-2">
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-black/50 border border-[var(--theme-border)] hover:bg-[var(--theme-border)] text-[var(--theme-primary)] transition-all cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Create File</span>
          </button>

          <button
            onClick={handleExportAll}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-[var(--theme-primary)] text-black font-semibold hover:opacity-90 transition-opacity cursor-pointer"
            title="Download full /out directory as a structured bundle"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export /out Workspace</span>
          </button>

          <button
            onClick={reload}
            className="p-1.5 rounded hover:bg-white/10 text-stone-400 hover:text-white transition-colors cursor-pointer"
            title="Refresh Files"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main Split: Left file list, Right preview drawer */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
        {/* Left: Filter and File List */}
        <div className="w-full md:w-5/12 border-r border-[var(--theme-border)] flex flex-col bg-black/20">
          {/* Search & Categories */}
          <div className="p-3 border-b border-[var(--theme-border)] space-y-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-stone-500 absolute left-2.5 top-2.5" />
              <input
                type="text"
                placeholder="Search artifacts by name or path..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-black/60 border border-[var(--theme-border)] rounded pl-8 pr-3 py-1.5 text-xs text-stone-200 placeholder-stone-600 focus:outline-none focus:border-[var(--theme-primary)]"
              />
            </div>
            <div className="flex items-center space-x-1 overflow-x-auto no-scrollbar pt-1">
              {categories.map((cat) => (
                <button
                  key={cat}
                  onClick={() => {
                    setSelectedCategory(cat);
                    sound.playKeypress();
                  }}
                  className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase transition-colors cursor-pointer ${
                    selectedCategory === cat
                      ? 'bg-[var(--theme-primary)] text-black font-bold'
                      : 'bg-black/40 border border-[var(--theme-border)] text-stone-400 hover:text-stone-200'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* File Items List */}
          <div className="flex-1 overflow-y-auto divide-y divide-[var(--theme-border)]/40 p-2 space-y-1">
            {filtered.length === 0 ? (
              <div className="text-center py-12 text-stone-500">
                No artifacts found matching filter.
              </div>
            ) : (
              filtered.map((item) => (
                <div
                  key={item.path}
                  onClick={() => {
                    setSelectedArtifact(item);
                    sound.playKeypress();
                  }}
                  className={`p-2.5 rounded cursor-pointer transition-all ${
                    selectedArtifact?.path === item.path
                      ? 'bg-[var(--theme-surface)] border border-[var(--theme-primary)] text-white'
                      : 'hover:bg-white/5 text-stone-300'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2 min-w-0">
                      <FileCode className="w-4 h-4 text-[var(--theme-primary)] shrink-0" />
                      <span className="font-semibold truncate text-xs">{item.filename}</span>
                    </div>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-black/50 text-stone-400 border border-[var(--theme-border)] shrink-0">
                      {(item.size / 1024).toFixed(1)} KB
                    </span>
                  </div>
                  <div className="text-[11px] text-stone-500 font-mono mt-1 truncate">
                    {item.path}
                  </div>
                  <div className="flex items-center justify-between mt-1 text-[10px] text-stone-500">
                    <span className="capitalize text-[var(--theme-dim)]">[{item.category}]</span>
                    <span>{item.createdAt}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right: Preview & Artifact Operations */}
        <div className="flex-1 flex flex-col bg-black/40 overflow-hidden">
          {selectedArtifact ? (
            <div className="flex-1 flex flex-col h-full overflow-hidden">
              {/* Preview Header */}
              <div className="px-4 py-2.5 border-b border-[var(--theme-border)] bg-[var(--theme-surface)]/80 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-bold text-xs text-[var(--theme-primary)] flex items-center space-x-2">
                    <FileText className="w-4 h-4" />
                    <span>{selectedArtifact.path}</span>
                  </div>
                  <div className="text-[11px] text-stone-400 mt-0.5">
                    {selectedArtifact.description}
                  </div>
                </div>

                {/* Operations */}
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => {
                      setViewHex(!viewHex);
                      sound.playKeypress();
                    }}
                    className={`flex items-center space-x-1 px-2.5 py-1 rounded border text-[11px] transition-colors cursor-pointer ${
                      viewHex
                        ? 'bg-[var(--theme-primary)] text-black font-semibold border-[var(--theme-primary)]'
                        : 'border-[var(--theme-border)] text-stone-300 hover:text-white'
                    }`}
                  >
                    <Binary className="w-3.5 h-3.5" />
                    <span>Hex Dump</span>
                  </button>

                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(selectedArtifact.content);
                      setIsCopied(true);
                      sound.playSuccess();
                      setTimeout(() => setIsCopied(false), 2000);
                    }}
                    className="flex items-center space-x-1 px-2.5 py-1 rounded border border-[var(--theme-border)] bg-black/40 text-stone-300 hover:text-white transition-colors cursor-pointer text-[11px]"
                  >
                    {isCopied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Eye className="w-3.5 h-3.5" />}
                    <span>{isCopied ? 'Copied' : 'Copy'}</span>
                  </button>

                  <button
                    onClick={() => handleDownload(selectedArtifact)}
                    className="flex items-center space-x-1 px-2.5 py-1 rounded bg-[var(--theme-primary)] text-black font-semibold hover:opacity-90 transition-opacity cursor-pointer text-[11px]"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download</span>
                  </button>

                  {onRunTerminalCommand && (
                    <button
                      onClick={() => {
                        onRunTerminalCommand(`cat ${selectedArtifact.path}`);
                        sound.playKeypress();
                      }}
                      className="flex items-center space-x-1 px-2.5 py-1 rounded border border-[var(--theme-border)] hover:bg-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] transition-colors cursor-pointer text-[11px]"
                      title="Inspect inside terminal"
                    >
                      <Share2 className="w-3.5 h-3.5" />
                      <span>Cat to CLI</span>
                    </button>
                  )}

                  <button
                    onClick={() => handleDelete(selectedArtifact.path)}
                    className="p-1 rounded text-rose-400 hover:bg-rose-950/60 border border-rose-900/40 transition-colors cursor-pointer"
                    title="Delete artifact"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Preview Content Area */}
              <div className="flex-1 p-4 overflow-y-auto font-mono text-xs text-stone-200 bg-black/70 select-text">
                {viewHex ? (
                  <pre className="text-emerald-400 whitespace-pre leading-relaxed select-text">
                    {toHexDump(selectedArtifact.content)}
                  </pre>
                ) : (
                  <pre className="whitespace-pre-wrap leading-relaxed select-text font-mono">
                    {selectedArtifact.content}
                  </pre>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-stone-500 p-6 text-center">
              <FolderDown className="w-12 h-12 mb-3 opacity-30 text-[var(--theme-primary)]" />
              <p className="text-sm font-semibold">Select an artifact to preview and download</p>
              <p className="text-xs text-stone-600 mt-1 max-w-sm">
                Files generated during natural language queries or terminal execution are automatically preserved here in the <code className="text-stone-400">/out</code> directory.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Modal for creating a file manually in /out */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="bg-[var(--theme-surface)] border border-[var(--theme-border)] rounded-lg w-full max-w-md p-4 box-glow space-y-3">
            <div className="flex justify-between items-center text-sm font-bold text-[var(--theme-primary)]">
              <span>Create New Artifact in /out</span>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-stone-400 hover:text-white cursor-pointer"
              >
                &times;
              </button>
            </div>
            <div>
              <label className="text-[11px] text-stone-400">File Path (Must start with /out/):</label>
              <input
                type="text"
                value={newFilePath}
                onChange={(e) => setNewFilePath(e.target.value)}
                className="w-full bg-black/70 border border-[var(--theme-border)] rounded px-2.5 py-1 text-xs text-emerald-300 font-mono mt-1"
              />
            </div>
            <div>
              <label className="text-[11px] text-stone-400">File Content:</label>
              <textarea
                rows={5}
                value={newFileContent}
                onChange={(e) => setNewFileContent(e.target.value)}
                className="w-full bg-black/70 border border-[var(--theme-border)] rounded p-2 text-xs text-stone-200 font-mono mt-1"
              />
            </div>
            <div className="flex justify-end space-x-2 pt-2">
              <button
                onClick={() => setShowCreateModal(false)}
                className="px-3 py-1 rounded border border-stone-700 text-stone-300 hover:bg-stone-800 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateFile}
                className="px-3 py-1 rounded bg-[var(--theme-primary)] text-black font-semibold hover:opacity-90 cursor-pointer"
              >
                Save to /out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
