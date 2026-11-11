const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const KEY = "sovereign_token";

export const getToken = () => localStorage.getItem(KEY);
export const setToken = (t) => (t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY));

async function call(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (getToken()) headers.Authorization = `Bearer ${getToken()}`;
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { ...options, headers });
  } catch {
    throw new Error("Cannot reach the server. Is the backend running on port 8000?");
  }
  if (res.status === 401) { setToken(null); throw Object.assign(new Error("Please sign in again."), { auth: true }); }
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : d?.message || `Request failed (${res.status})`);
  }
  return body;
}

export async function login(email, password) {
  const data = await call("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
  setToken(data.access_token);
  return data.user;
}
export const me = () => call("/api/v1/auth/me");
export const logout = () => call("/api/v1/auth/logout", { method: "POST" }).catch(() => {}).finally(() => setToken(null));
export const listDocuments = () => call("/api/v1/documents?limit=100");
export const uploadDocument = (file) => {
  const form = new FormData();
  form.append("file", file);
  return call("/api/v1/documents", { method: "POST", body: form });
};
export const indexAll = () => call("/api/v1/index", { method: "POST" });
export const ask = (query) =>
  call("/api/v1/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, top_k: 5 }) });

export const agents = () => call("/api/v1/agents");
export const runAgent = (name, task) =>
  call(`/api/v1/agents/${name}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task }) });
export const auditList = () => call("/api/v1/audit?limit=15");
export const auditVerify = () => call("/api/v1/audit/verify");
export const usageSummary = () => call("/api/v1/usage/summary");
export const users = () => call("/api/v1/users");
