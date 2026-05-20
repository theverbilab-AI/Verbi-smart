// VITE_API_URL is set in Netlify; production fallback matches Railway backend
const API_ROOT =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.PROD
    ? "https://verbilabcare-production.up.railway.app"
    : "http://localhost:5000");
const BASE = `${API_ROOT}/api/v1`;
const AUTH = `${API_ROOT}/api/auth`;
function getToken() {
  return localStorage.getItem("care_token") || "";
}

function authHeaders() {
  return {
    "Authorization": `Bearer ${getToken()}`,
    "Content-Type": "application/json",
  };
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export async function login(email, password) {
  const res = await fetch(`${AUTH}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Login failed");
  return data;
}

export async function getMe() {
  const res = await fetch(`${AUTH}/me`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Not authenticated");
  return res.json();
}

export function logout() {
  localStorage.removeItem("care_token");
  localStorage.removeItem("care_user");
}

// ── Calls ─────────────────────────────────────────────────────────────────────
export async function uploadCall(file, metadata = {}, onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);
    Object.entries(metadata).forEach(([k, v]) => { if (v) formData.append(k, v); });

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/calls/ingest`);
    xhr.setRequestHeader("Authorization", `Bearer ${getToken()}`);

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
    }
    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 201) {
        resolve(JSON.parse(xhr.responseText));
        return;
      }
      let msg = `Upload failed (${xhr.status})`;
      try {
        const body = JSON.parse(xhr.responseText);
        if (body.error) msg = body.error;
        else if (body.detail) msg = `${body.error || msg}: ${body.detail}`;
      } catch (_e) { /* ignore */ }
      reject(new Error(msg));
    };
    xhr.onerror = () => reject(new Error("Cannot reach backend. Is Flask running?"));
    xhr.send(formData);
  });
}

export async function getCalls(params = {}) {
  const qs = new URLSearchParams({ limit: 50, ...params }).toString();
  const res = await fetch(`${BASE}/calls?${qs}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getCalls failed (${res.status})`);
  return res.json();
}

/** Fetch audio with auth headers — returns blob URL for <audio src>. */
export async function fetchCallAudioBlob(callId) {
  const token = getToken();
  const res = await fetch(getCallAudioUrl(callId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: "include",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg = [err.error, err.hint].filter(Boolean).join(" — ");
    throw new Error(msg || `Audio failed (${res.status})`);
  }
  const blob = await res.blob();
  if (!blob.size) throw new Error("Audio file is empty on server");
  if (blob.type && !blob.type.startsWith("audio/") && blob.type !== "application/octet-stream") {
    throw new Error("Server did not return audio — check S3 credentials and redeploy backend");
  }
  return URL.createObjectURL(blob);
}

/** Upload multiple files with limited concurrency (default 3). */
export async function uploadCallsBatch(files, metadata = {}, onFileProgress) {
  const queue = [...files];
  const results = [];
  const errors = [];
  const workers = 3;

  async function worker() {
    while (queue.length) {
      const file = queue.shift();
      if (!file) break;
      try {
        const res = await uploadCall(file, metadata, (pct) => onFileProgress?.(file.name, pct));
        results.push(res);
      } catch (err) {
        errors.push({ file: file.name, error: err.message });
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(workers, files.length) }, () => worker()));
  return { results, errors };
}

export async function getCall(callId) {
  const res = await fetch(`${BASE}/calls/${callId}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getCall failed (${res.status})`);
  return res.json();
}

/** Full URL for HTML5 audio player (includes auth token for browser playback). */
export function getCallAudioUrl(callId) {
  const token = getToken();
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${API_ROOT}/api/v1/calls/${callId}/audio${qs}`;
}

export async function getDashboard(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${BASE}/reports/dashboard${qs ? "?" + qs : ""}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getDashboard failed (${res.status})`);
  return res.json();
}

export async function getAgentKPIs() {
  const res = await fetch(`${BASE}/agents/kpis`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getAgentKPIs failed (${res.status})`);
  return res.json();
}

// ── Export CSV ────────────────────────────────────────────────────────────────
export async function downloadDispositionLoans(disposition, params = {}) {
  const qs = new URLSearchParams({ disposition, ...params }).toString();
  const res = await fetch(`${BASE}/reports/disposition-loans?${qs}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Download failed (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `CARE_${String(disposition).toLowerCase()}_loan_ids.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadCSVExport(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const url = `${BASE}/reports/export${qs ? "?" + qs : ""}`;
  // Create a link with auth header workaround — open in new tab
  const a = document.createElement("a");
  a.href = url;
  a.download = `CARE_Export_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
}

// ── Google Drive Sync ─────────────────────────────────────────────────────────
export async function syncGDrive(folderIdOrUrl = null) {
  const res = await fetch(`${BASE}/connectors/gdrive/sync`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(folderIdOrUrl ? { folder_id: folderIdOrUrl } : {}),
  });
  if (!res.ok) throw new Error(`Drive sync failed (${res.status})`);
  return res.json();
}

export async function saveGDriveConfig(folderUrl, autoSync = false) {
  const res = await fetch(`${BASE}/connectors/gdrive/config`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ folder_url: folderUrl, auto_sync: autoSync }),
  });
  if (!res.ok) throw new Error("Failed to save Drive config");
  return res.json();
}

// ── S3 Ingest ─────────────────────────────────────────────────────────────────
async function parseApiError(res, fallback) {
  const body = await res.json().catch(() => ({}));
  const msg = body.error || body.message || fallback;
  const detail = body.detail || body.hint;
  return detail ? `${msg} — ${detail}` : msg;
}

export async function ingestFromS3(s3Uri, metadata = {}) {
  const res = await fetch(`${BASE}/calls/ingest-s3`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ s3_uri: s3Uri, ...metadata }),
  });
  if (!res.ok) throw new Error(await parseApiError(res, `S3 ingest failed (${res.status})`));
  return res.json();
}

export async function ingestFromUrl(url, metadata = {}) {
  const res = await fetch(`${BASE}/calls/ingest-url`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ url, ...metadata }),
  });
  if (!res.ok) throw new Error(await parseApiError(res, `URL ingest failed (${res.status})`));
  return res.json();
}
