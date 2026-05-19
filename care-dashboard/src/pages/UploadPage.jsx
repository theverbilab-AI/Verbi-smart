import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { uploadCallsBatch, getCalls, ingestFromUrl, ingestFromS3 } from "../services/api";

const STATUS_COLOR = {
  processed: "text-green-400", processing: "text-yellow-400",
  transcribing: "text-yellow-400", scoring: "text-yellow-400",
  queued: "text-blue-400", fetching: "text-blue-400", failed: "text-red-400",
};

const TABS = ["📁 Upload File", "🔗 Drive / URL", "☁️ S3 Bucket"];

export default function UploadPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState(0);
  const [files, setFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [recentUploads, setRecentUploads] = useState([]);
  const [loadingUploads, setLoadingUploads] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");
  const [metadata, setMetadata] = useState({ agent_id: "", campaign_id: "", date: "", loan_id: "" });
  const [driveUrl, setDriveUrl] = useState("");
  const [urlMeta, setUrlMeta] = useState({ agent_id: "", loan_id: "" });
  const [urlLoading, setUrlLoading] = useState(false);
  const [urlMsg, setUrlMsg] = useState(null);
  const [s3Uri, setS3Uri] = useState("");
  const [s3Meta, setS3Meta] = useState({ agent_id: "", loan_id: "" });
  const [s3Loading, setS3Loading] = useState(false);
  const [s3Msg, setS3Msg] = useState(null);

  const fetchUploads = useCallback(async (silent = false) => {
    if (!silent) setLoadingUploads(true);
    else setRefreshing(true);
    try {
      const data = await getCalls({ limit: 40 });
      setRecentUploads(Array.isArray(data) ? data : data.calls ?? []);
    } catch (e) { console.error(e); }
    finally {
      setLoadingUploads(false);
      setRefreshing(false);
    }
  }, []);

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
      const res = await ingestFromUrl(driveUrl.trim(), urlMeta);
      setUrlMsg({ ok: true, text: `✅ Queued — Call ID: ${res.call_id}` });
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
          <p className="text-xs text-gray-400 mb-4">Paste a Google Drive link or any direct audio URL. Drive files must be shared as <span className="text-cyan-400">"Anyone with link"</span>.</p>
          <label className="block text-sm text-gray-400 mb-1.5">Drive Link or Audio URL</label>
          <input type="text" value={driveUrl} onChange={e => setDriveUrl(e.target.value)}
            placeholder="https://drive.google.com/file/d/... or https://..."
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
            {urlLoading ? "Queuing…" : "🔗 Fetch & Process"}
          </button>
          <div className="mt-4 bg-gray-700/50 rounded-lg p-3 text-xs text-gray-500 space-y-0.5">
            <p className="text-gray-400 font-medium mb-1">Supported formats:</p>
            <p>• https://drive.google.com/file/d/FILE_ID/view</p>
            <p>• https://drive.google.com/open?id=FILE_ID</p>
            <p>• Any direct .mp3 / .wav / .m4a / .ogg / .flac URL</p>
          </div>
        </div>
      )}

      {tab === 2 && (
        <div className="bg-gray-800 rounded-xl p-6">
          <h2 className="font-semibold text-gray-200 mb-1">Amazon S3 File</h2>
          <p className="text-xs text-gray-400 mb-1">Enter the S3 URI of an audio file. S3 is the <strong className="text-gray-300">source</strong> — clients upload recordings there, CARE pulls and processes them.</p>
          <div className="bg-blue-900/30 border border-blue-700 rounded-lg px-3 py-2 text-xs text-blue-300 mb-4">
            ℹ Bucket: <span className="font-mono">verbilab-care-audio-2026</span> (eu-north-1)
          </div>
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
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">Recent Uploads</h2>
          <button onClick={() => fetchUploads(true)} className="text-xs text-cyan-400 hover:text-cyan-300">
            {refreshing ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>
        {loadingUploads && recentUploads.length === 0 ? (
          <p className="text-gray-400 text-sm animate-pulse">Loading…</p>
        ) : recentUploads.length === 0 ? <p className="text-gray-500 text-sm">No uploads yet.</p>
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
                    {call.score != null && call.status === "processed" && <span className="text-xs text-gray-300 font-mono">{call.score}/20</span>}
                    <span className={`text-xs font-semibold uppercase ${STATUS_COLOR[call.status] ?? "text-gray-400"}`}>● {call.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
      </div>
    </div>
  );
}