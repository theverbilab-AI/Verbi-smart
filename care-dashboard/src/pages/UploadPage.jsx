import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  uploadCallsBatch,
  getCalls,
  callsFromResponse,
  ingestFromUrl,
  ingestFromS3,
  syncGDrive,
  saveGDriveConfig,
  purgeCalls,
} from "../services/api";
import PaginationBar from "../components/PaginationBar";
import { getStoredUser, hasPermission } from "../utils/permissions";

const PAGE_SIZE = 10;

function isDriveFolderUrl(url) {
  return /drive\.google\.com\/(drive\/)?folders\//.test((url || "").trim());
}

const TABS = ["Local Upload", "Google Drive / URL", "Amazon S3"];

const STATUS_COLOR = {
  processed: "text-green-400", processing: "text-yellow-400",
  transcribing: "text-yellow-400", scoring: "text-yellow-400",
  queued: "text-blue-400", fetching: "text-blue-400", failed: "text-red-400",
};

function AuditModeSelect({ value, onChange }) {
  const opts = [
    { id: "collections", label: "Collections QA", desc: "Recovery / PTP audit" },
    { id: "sales", label: "Sales QA", desc: "16-KPI sales audit" },
  ];
  return (
    <div className="mb-4">
      <label className="block text-sm font-medium text-gray-300 mb-2">Audit Type</label>
      <div className="grid grid-cols-2 gap-2">
        {opts.map((o) => {
          const active = value === o.id;
          return (
            <button
              key={o.id}
              type="button"
              onClick={() => onChange(o.id)}
              className={`text-left rounded-lg border px-4 py-2.5 transition-colors ${
                active
                  ? "border-cyan-500 bg-cyan-900/30 text-white"
                  : "border-gray-600 bg-gray-800/50 text-gray-400 hover:border-gray-500"
              }`}
            >
              <span className="flex items-center gap-2 text-sm font-semibold">
                <span
                  className={`inline-block w-2 h-2 rounded-full ${active ? "bg-cyan-400" : "bg-gray-600"}`}
                />
                {o.label}
              </span>
              <span className="block text-xs text-gray-500 mt-0.5">{o.desc}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function matchesCallSearch(call, q) {
  if (!q) return true;
  const hay = [
    call.id, call.filename, call.agent_id, call.agent_name,
    call.loan_id, call.customer_id, call.disposition, call.status,
  ].filter(Boolean).join(" ").toLowerCase();
  return hay.includes(q.toLowerCase());
}

export default function UploadPage() {
  const navigate = useNavigate();
  const canDeleteCalls = hasPermission(getStoredUser(), "delete_calls");
  const [tab, setTab] = useState(0);
  const [files, setFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [recentUploads, setRecentUploads] = useState([]);
  const [loadingUploads, setLoadingUploads] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [uploadsError, setUploadsError] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [agentFilter, setAgentFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [uploadStatus, setUploadStatus] = useState("");
  const [metadata, setMetadata] = useState({ agent_id: "", campaign_id: "", date: "", loan_id: "", audit_mode: "collections" });
  const [driveUrl, setDriveUrl] = useState("");
  const [urlMeta, setUrlMeta] = useState({ agent_id: "", loan_id: "", audit_mode: "collections" });
  const [urlLoading, setUrlLoading] = useState(false);
  const [urlMsg, setUrlMsg] = useState(null);
  const [s3Uri, setS3Uri] = useState("");
  const [s3Meta, setS3Meta] = useState({ agent_id: "", loan_id: "", audit_mode: "collections" });
  const [s3Loading, setS3Loading] = useState(false);
  const [s3Msg, setS3Msg] = useState(null);
  const [purging, setPurging] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, agentFilter, statusFilter]);

  const fetchUploads = useCallback(async (silent = false) => {
    if (!silent) setLoadingUploads(true);
    else setRefreshing(true);
    try {
      setUploadsError("");
      const hasFilter = Boolean(debouncedSearch || agentFilter.trim() || statusFilter);
      const params = {
        page: hasFilter ? 1 : page,
        limit: hasFilter ? 100 : PAGE_SIZE,
      };
      if (debouncedSearch) params.search = debouncedSearch;
      if (agentFilter.trim()) params.agent_id = agentFilter.trim();
      if (statusFilter) params.status = statusFilter;
      const data = await getCalls(params);
      let list = callsFromResponse(data);
      if (debouncedSearch) {
        list = list.filter((c) => matchesCallSearch(c, debouncedSearch));
      }
      if (agentFilter.trim()) {
        const a = agentFilter.trim().toLowerCase();
        list = list.filter((c) =>
          String(c.agent_id || "").toLowerCase().includes(a) ||
          String(c.agent_name || "").toLowerCase().includes(a) ||
          String(c.filename || "").toLowerCase().includes(a)
        );
      }
      if (hasFilter) {
        const totalFiltered = list.length;
        const start = (page - 1) * PAGE_SIZE;
        list = list.slice(start, start + PAGE_SIZE);
        setTotal(totalFiltered);
        setPages(Math.max(1, Math.ceil(totalFiltered / PAGE_SIZE)));
      } else {
        setTotal(data.total ?? list.length);
        setPages(data.pages ?? 1);
      }
      setRecentUploads(list);
    } catch (e) {
      console.error(e);
      setUploadsError(e.message || "Could not load recent uploads.");
    } finally {
      setLoadingUploads(false);
      setRefreshing(false);
    }
  }, [page, debouncedSearch, agentFilter, statusFilter]);

  useEffect(() => {
    fetchUploads(false);
    const t = setInterval(() => {
      if (document.visibilityState === "visible") fetchUploads(true);
    }, 15000);
    return () => clearInterval(t);
  }, [fetchUploads]);

  const addFiles = (list) => {
    const picked = Array.from(list || []).filter(Boolean);
    if (!picked.length) return;
    setFiles((prev) => [...prev, ...picked]);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const handleUpload = async () => {
    if (!files.length) return;
    setUploading(true);
    setProgress(0);
    setUploadStatus("");
    try {
      const { results, errors } = await uploadCallsBatch(files, metadata, (name, pct) => {
        setUploadStatus(`Uploading ${name}… ${pct}%`);
        setProgress(pct);
      });
      setFiles([]);
      setProgress(100);
      setUploadStatus(
        `✅ Queued ${results.length} file(s)` + (errors.length ? ` · ${errors.length} failed` : ""),
      );
      await fetchUploads(true);
    } catch (e) {
      alert("Upload failed: " + e.message);
    } finally {
      setUploading(false);
    }
  };

  const handleUrlIngest = async () => {
    if (!driveUrl.trim()) return;
    setUrlLoading(true); setUrlMsg(null);
    try {
      const url = driveUrl.trim();
      if (isDriveFolderUrl(url)) {
        await saveGDriveConfig(url, false);
        const res = await syncGDrive(url);
        const n = res.synced ?? (res.calls?.length ?? 0);
        if (res.message && !n) {
          setUrlMsg({ ok: false, text: res.message });
        } else {
          setUrlMsg({ ok: true, text: `✅ Queued ${n} file(s) from Drive folder` });
        }
      } else {
        const res = await ingestFromUrl(url, urlMeta);
        setUrlMsg({ ok: true, text: `✅ Queued — Call ID: ${res.call_id}` });
      }
      setDriveUrl(""); await fetchUploads(true);
    } catch (e) { setUrlMsg({ ok: false, text: `❌ ${e.message}` }); }
    finally { setUrlLoading(false); }
  };

  const handleS3Ingest = async () => {
    if (!s3Uri.trim()) return;
    setS3Loading(true); setS3Msg(null);
    try {
      const res = await ingestFromS3(s3Uri.trim(), s3Meta);
      setS3Msg({ ok: true, text: `✅ Queued — Call ID: ${res.call_id}` });
      setS3Uri(""); await fetchUploads(true);
    } catch (e) { setS3Msg({ ok: false, text: `❌ ${e.message}` }); }
    finally { setS3Loading(false); }
  };

  const fmtSize = b => b >= 1048576 ? (b/1048576).toFixed(1)+" MB" : (b/1024).toFixed(0)+" KB";
  const fmtDate = ts => ts ? new Date(ts).toLocaleString("en-IN") : "";

  return (
    <div className="p-6 max-w-3xl mx-auto text-white">
      <h1 className="text-2xl font-bold mb-6">Upload Document</h1>
      <div className="flex gap-1 bg-gray-800 rounded-xl p-1 mb-6 w-fit">
        {TABS.map((t, i) => (
          <button key={t} onClick={() => setTab(i)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${tab === i ? "bg-cyan-600 text-white" : "text-gray-400 hover:text-white"}`}>
            {t}
          </button>
        ))}
      </div>

      {tab === 0 && (
        <div>
          <AuditModeSelect
            value={metadata.audit_mode}
            onChange={(v) => setMetadata((m) => ({ ...m, audit_mode: v }))}
          />
          <div onDragOver={e => { e.preventDefault(); setIsDragging(true); }} onDragLeave={() => setIsDragging(false)} onDrop={handleDrop}
            className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors ${isDragging ? "border-cyan-400 bg-cyan-900/20" : "border-gray-600 bg-gray-800/50"}`}>
            <div className="text-4xl mb-3">☁️</div>
            <p className="font-semibold text-lg">Drag & Drop Audio Files</p>
            <p className="text-gray-400 text-sm mb-4">or click to browse from your computer</p>
            <div className="flex flex-wrap justify-center gap-2 mb-3">
              {[".mp3",".wav",".m4a",".ogg",".flac",".aac",".wma",".zip"].map(e => (
                <span key={e} className="bg-gray-700 rounded-full px-3 py-0.5 text-xs">{e}</span>
              ))}
            </div>
            <p className="text-xs text-gray-500 mb-4">Max 500 MB · All audio formats supported</p>
            <input type="file" multiple accept=".mp3,.wav,.m4a,.ogg,.flac,.aac,.wma,.zip,.csv" className="hidden" id="file-input" onChange={e => addFiles(e.target.files)} />
            <label htmlFor="file-input" className="cursor-pointer bg-cyan-600 hover:bg-cyan-500 px-5 py-2 rounded-lg text-sm font-medium transition-colors">Browse Files</label>
          </div>
          {files.length > 0 && (
            <div className="mt-4 space-y-2">
              {files.map((f, i) => (
                <div key={`${f.name}-${i}`} className="bg-gray-800 rounded-lg p-4 flex items-center justify-between">
                  <div><p className="font-medium">{f.name}</p><p className="text-xs text-gray-400">{fmtSize(f.size)}</p></div>
                  <button type="button" onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))} className="text-gray-400 hover:text-white text-xl">×</button>
                </div>
              ))}
            </div>
          )}
          {files.length > 0 && (
            <div className="mt-4 bg-gray-800/60 rounded-lg p-4">
              <p className="text-sm font-medium mb-3 text-gray-300">Metadata (Optional)</p>
              <div className="grid grid-cols-2 gap-3">
                {[["Agent ID","agent_id"],["Campaign ID","campaign_id"],["Date (YYYYMMDD)","date"],["Loan ID","loan_id"]].map(([l,k]) => (
                  <input key={k} type="text" placeholder={l} value={metadata[k]} onChange={e => setMetadata(m => ({...m,[k]:e.target.value}))}
                    className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-cyan-500 outline-none" />
                ))}
              </div>
            </div>
          )}
          {uploading && (
            <div className="mt-3">
              <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                <div className="h-full bg-cyan-400 transition-all" style={{ width: `${progress}%` }} />
              </div>
              <p className="text-xs text-gray-400 mt-1">{progress}% uploaded…</p>
            </div>
          )}
          {uploadStatus && <p className="mt-2 text-xs text-cyan-400">{uploadStatus}</p>}
          {files.length > 0 && !uploading && (
            <button onClick={handleUpload} className="mt-4 w-full bg-cyan-500 hover:bg-cyan-400 text-black font-semibold py-3 rounded-xl transition-colors">
              ⬆ Upload {files.length} file{files.length > 1 ? "s" : ""} for Processing
            </button>
          )}
        </div>
      )}

      {tab === 1 && (
        <div className="bg-gray-800 rounded-xl p-6">
          <h2 className="font-semibold text-gray-200 mb-1">Google Drive or Direct URL</h2>
          <p className="text-xs text-gray-400 mb-4">
            Paste a <span className="text-cyan-400">Drive folder link</span> for bulk sync, a single file link, or any direct audio URL.
            Files must be shared as <span className="text-cyan-400">"Anyone with link"</span>.
          </p>
          <AuditModeSelect
            value={urlMeta.audit_mode}
            onChange={(v) => setUrlMeta((m) => ({ ...m, audit_mode: v }))}
          />
          <label className="block text-sm text-gray-400 mb-1.5">Drive folder, file link, or audio URL</label>
          <input type="text" value={driveUrl} onChange={e => setDriveUrl(e.target.value)}
            placeholder="https://drive.google.com/drive/folders/... or file link"
            className="w-full bg-gray-700 rounded-lg px-4 py-3 text-sm border border-gray-600 focus:border-cyan-500 outline-none mb-4" />
          <div className="grid grid-cols-2 gap-3 mb-5">
            <input type="text" placeholder="Agent ID (optional)" value={urlMeta.agent_id} onChange={e => setUrlMeta(m => ({...m, agent_id: e.target.value}))}
              className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-cyan-500 outline-none" />
            <input type="text" placeholder="Loan ID (optional)" value={urlMeta.loan_id} onChange={e => setUrlMeta(m => ({...m, loan_id: e.target.value}))}
              className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-cyan-500 outline-none" />
          </div>
          {urlMsg && <div className={`mb-4 px-4 py-3 rounded-lg text-sm ${urlMsg.ok ? "bg-green-900/40 text-green-300" : "bg-red-900/40 text-red-300"}`}>{urlMsg.text}</div>}
          <button onClick={handleUrlIngest} disabled={!driveUrl.trim() || urlLoading}
            className="w-full bg-cyan-500 hover:bg-cyan-400 disabled:bg-cyan-900 text-black font-semibold py-3 rounded-xl transition-colors">
            {urlLoading ? "Queuing…" : "🔗 Sync folder / Fetch & Process"}
          </button>
          <div className="mt-4 bg-gray-700/50 rounded-lg p-3 text-xs text-gray-500 space-y-0.5">
            <p className="text-gray-400 font-medium mb-1">Supported formats:</p>
            <p>• https://drive.google.com/drive/folders/FOLDER_ID (bulk — all audio in folder)</p>
            <p>• https://drive.google.com/file/d/FILE_ID/view</p>
            <p>• https://drive.google.com/open?id=FILE_ID</p>
            <p>• Any direct .mp3 / .wav / .m4a / .ogg / .flac URL</p>
          </div>
        </div>
      )}

      {tab === 2 && (
        <div className="bg-gray-800 rounded-xl p-6">
          <h2 className="font-semibold text-gray-200 mb-1">Amazon S3 File</h2>
          <p className="text-xs text-gray-400 mb-1">Enter the S3 URI of an audio file. S3 is the <strong className="text-gray-300">source</strong> — clients upload recordings there, VerbiSmart pulls and processes them.</p>
          <div className="bg-blue-900/30 border border-blue-700 rounded-lg px-3 py-2 text-xs text-blue-300 mb-4">
            ℹ Bucket: <span className="font-mono">verbilab-care-audio-2026</span> (eu-north-1)
          </div>
          <AuditModeSelect
            value={s3Meta.audit_mode}
            onChange={(v) => setS3Meta((m) => ({ ...m, audit_mode: v }))}
          />
          <label className="block text-sm text-gray-400 mb-1.5">S3 URI</label>
          <input type="text" value={s3Uri} onChange={e => setS3Uri(e.target.value)}
            placeholder="s3://verbilab-care-audio-2026/audio/recording.mp3"
            className="w-full bg-gray-700 rounded-lg px-4 py-3 text-sm font-mono border border-gray-600 focus:border-cyan-500 outline-none mb-4" />
          <div className="grid grid-cols-2 gap-3 mb-5">
            <input type="text" placeholder="Agent ID (optional)" value={s3Meta.agent_id} onChange={e => setS3Meta(m => ({...m, agent_id: e.target.value}))}
              className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-cyan-500 outline-none" />
            <input type="text" placeholder="Loan ID (optional)" value={s3Meta.loan_id} onChange={e => setS3Meta(m => ({...m, loan_id: e.target.value}))}
              className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-cyan-500 outline-none" />
          </div>
          {s3Msg && <div className={`mb-4 px-4 py-3 rounded-lg text-sm ${s3Msg.ok ? "bg-green-900/40 text-green-300" : "bg-red-900/40 text-red-300"}`}>{s3Msg.text}</div>}
          <button onClick={handleS3Ingest} disabled={!s3Uri.trim() || s3Loading}
            className="w-full bg-cyan-500 hover:bg-cyan-400 disabled:bg-cyan-900 text-black font-semibold py-3 rounded-xl transition-colors">
            {s3Loading ? "Queuing…" : "☁️ Fetch from S3 & Process"}
          </button>
        </div>
      )}

      {/* Recent Uploads */}
      <div className="mt-8">
        <div className="flex items-center justify-between gap-3 mb-3">
          <h2 className="text-lg font-semibold">Recent Uploads</h2>
          <div className="flex items-center gap-3">
            {canDeleteCalls && (
              <button
                type="button"
                disabled={purging || total === 0}
                onClick={async () => {
                  const ok = window.confirm(
                    `Delete ALL ${total || ""} past recordings from the database?\n\nThis cannot be undone. Audio files in S3 (if any) are not removed.`
                  );
                  if (!ok) return;
                  const typed = window.prompt('Type PURGE to confirm clearing all past recordings:');
                  if ((typed || "").trim().toUpperCase() !== "PURGE") return;
                  setPurging(true);
                  try {
                    const result = await purgeCalls({ keep: 0 });
                    setUploadsError("");
                    setUploadStatus(
                      `Cleared ${result.deleted ?? 0} recording(s). List refreshed.`
                    );
                    setPage(1);
                    await fetchUploads();
                  } catch (e) {
                    setUploadsError(e.message || "Could not clear recordings.");
                  } finally {
                    setPurging(false);
                  }
                }}
                className="text-xs text-red-400 hover:text-red-300 disabled:opacity-40"
              >
                {purging ? "Clearing…" : "Clear all"}
              </button>
            )}
            <button onClick={() => fetchUploads(true)} className="text-xs text-cyan-400 hover:text-cyan-300">
              {refreshing ? "Refreshing…" : "↻ Refresh"}
            </button>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 mb-3">
          <input
            type="search"
            placeholder="Search call ID, filename, loan…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 min-w-[180px] bg-gray-800 rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-cyan-500 outline-none"
          />
          <input
            type="text"
            placeholder="Agent ID"
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            className="w-32 bg-gray-800 rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-cyan-500 outline-none"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-gray-800 rounded-lg px-3 py-2 text-sm border border-gray-600"
          >
            <option value="">All status</option>
            <option value="processed">Processed</option>
            <option value="failed">Failed</option>
            <option value="queued">Queued</option>
            <option value="transcribing">Transcribing</option>
          </select>
        </div>
        {uploadsError && (
          <div className="mb-3 bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-2 text-sm">
            ⚠ {uploadsError}
          </div>
        )}
        {loadingUploads && recentUploads.length === 0 ? (
          <p className="text-gray-400 text-sm animate-pulse">Loading…</p>
        ) : recentUploads.length === 0 && !uploadsError ? (
          <p className="text-gray-500 text-sm">
            {debouncedSearch || agentFilter ? "No matching uploads." : "No uploads yet."}
          </p>
        )
          : (
            <div className="space-y-2">
              {recentUploads.map(call => (
                <div key={call.id} onClick={() => navigate(`/calls/${call.id}`)}
                  className="bg-gray-800 rounded-lg px-4 py-3 flex items-center justify-between cursor-pointer hover:bg-gray-700 transition-colors">
                  <div>
                    <p className="text-sm font-medium">{call.filename ?? call.id}</p>
                    <p className="text-xs text-gray-400">
                      {call.file_size ? fmtSize(call.file_size) + " · " : ""}{fmtDate(call.uploaded_at)}
                      {call.source && call.source !== "upload" && <span className="ml-2 text-cyan-500 capitalize">· {call.source}</span>}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    {call.score != null && call.status === "processed" && (
                      <span className="text-xs text-gray-300 font-mono">
                        {(call.analysis?.audit_mode || "").toLowerCase() === "sales"
                          ? `${call.score}/100`
                          : `${call.score}/20`}
                      </span>
                    )}
                    <span className={`text-xs font-semibold uppercase ${STATUS_COLOR[call.status] ?? "text-gray-400"}`}>● {call.status}</span>
                  </div>
                </div>
              ))}
              <PaginationBar
                page={page}
                pages={pages}
                total={total}
                pageSize={PAGE_SIZE}
                onPageChange={setPage}
              />
            </div>
          )}
      </div>
    </div>
  );
}