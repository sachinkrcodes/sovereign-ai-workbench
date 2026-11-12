import { useEffect, useState } from "react";
import * as api from "./api.js";
import { Agents } from "./Extra.jsx";
import Admin from "./Admin.jsx";
import { Dock, ThemeButton, toast, useElapsed } from "./ui.jsx";

const clip = (t, n = 240) => (t.length > n ? t.slice(0, n) + "…" : t);

function Login({ onDone }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError("");
    try { onDone(await api.login(email, password)); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return (
    <main className="auth-wrap">
      <form className="glass auth-card" onSubmit={submit}>
        <h1>Sovereign AI</h1>
        <p className="sub">Ask questions about your company documents. Everything runs on your own machine.</p>
        <div className="field"><label htmlFor="em">Email</label>
          <input id="em" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></div>
        <div className="field"><label htmlFor="pw">Password</label>
          <input id="pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></div>
        <p className="error" role="alert">{error}</p>
        <button className="btn wide" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}

function Sources({ sources, cited }) {
  return (
    <div className="list">
      {sources.map((s) => (
        <div className="row wrap" key={s.ref}>
          <span className="mini">{s.ref}</span>
          <div className="grow">
            <b>{s.filename}{s.page_number ? `, page ${s.page_number}` : ""}</b>
            <small>{clip(s.text)}</small>
          </div>
          <span className={cited.has(s.ref) ? "chip good" : "chip none"}>{cited.has(s.ref) ? "Cited" : "Retrieved"}</span>
        </div>
      ))}
    </div>
  );
}

function Ask() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const secs = useElapsed(busy);
  async function submit(e) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true); setResult(null);
    try { setResult(await api.ask(query.trim())); }
    catch (err) { toast(err.message, true); }
    finally { setBusy(false); }
  }
  return (
    <div className="stack">
      <form className="glass panel" onSubmit={submit}>
        <div className="field"><label htmlFor="q">Your question</label>
          <textarea id="q" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="What does the shutdown procedure say about valve isolation?" /></div>
        <button className="btn wide" disabled={busy || !query.trim()}>{busy ? `Reading your documents… ${secs}s` : "Ask"}</button>
        {busy && <p className="hint">Your own AI is thinking on this computer. Most answers take 10 to 40 seconds.</p>}
      </form>
      {result && (
        <section className="glass panel" aria-live="polite">
          {result.answer ? <p className="answer-text">{result.answer}</p> : <p className="sub">The AI engine is unavailable, so these are the best matching passages.</p>}
          {result.notice && <div className="notice"><span className="chip warn">Note</span><span className="sub">{result.notice}</span></div>}
          {result.sources.length > 0 && <Sources sources={result.sources} cited={new Set(result.citations)} />}
          {result.mode === "no_results" && <p className="sub">Upload a document on the Documents tab, then index it.</p>}
        </section>
      )}
    </div>
  );
}

function Documents({ canEdit }) {
  const [docs, setDocs] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const load = () => api.listDocuments().then((d) => setDocs(d.items)).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);
  async function run(task, done) {
    setBusy(true);
    try { await task(); toast(done); await load(); }
    catch (e) { toast(e.message, true); }
    finally { setBusy(false); }
  }
  return (
    <div className="stack">
      {canEdit && (
        <section className="glass panel between">
          <label className="btn soft">Upload a document
            <input type="file" hidden accept=".pdf,.docx,.txt,.md" disabled={busy}
              onChange={(e) => e.target.files[0] && run(async () => { await api.uploadDocument(e.target.files[0]); await api.indexAll(); }, "Uploaded and ready to search.")} />
          </label>
          <button className="btn" disabled={busy} onClick={() => run(api.indexAll, "Indexing finished.")}>{busy ? "Working…" : "Re-index all"}</button>
        </section>
      )}
      <section className="glass panel">
        {docs === null ? <div className="loading"><div className="sk short" /></div>
          : docs.length === 0 ? <div className="empty"><h3>No documents yet</h3><p>Upload a PDF, Word, text or Markdown file.</p></div>
          : <div className="list">{docs.map((d) => (
              <div className="row" key={d.id}><span className="mini">{d.file_type.toUpperCase().slice(0, 3)}</span>
                <div className="grow"><b>{d.filename}</b><small>{d.page_count ? `${d.page_count} pages` : "text"}</small></div>
                <span className="chip none">{d.chunk_count} {d.chunk_count === 1 ? "passage" : "passages"}</span>
                {canEdit && <button className="btn danger small" onClick={() => setConfirm(d)}>Delete</button>}</div>))}</div>}
      </section>
      {confirm && (
        <div className="scrim" onClick={(e) => e.target === e.currentTarget && setConfirm(null)}>
          <div className="glass modal" role="dialog" aria-modal="true">
            <h2>Delete this document?</h2>
            <p className="sub">{confirm.filename} and its search index will be removed. This cannot be undone.</p>
            <div className="actions">
              <button className="btn soft" onClick={() => setConfirm(null)}>Cancel</button>
              <button className="btn" onClick={() => { const id = confirm.id; setConfirm(null); run(() => api.deleteDocument(id), "Document deleted."); }}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const HEADS = {
  ask: ["Ask your documents", "Answers come from your files and always show where they came from."],
  docs: ["Documents", "Upload files, then index them so they can be searched."],
  agents: ["Agents", "Helpers with limited permissions. Every step they take is recorded."],
  admin: ["Admin", "People, activity, agent runs and usage. Visible to admins only."],
};

export default function App() {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(!api.getToken());
  const [tab, setTab] = useState("ask");
  useEffect(() => { if (api.getToken()) api.me().then(setUser).catch(() => {}).finally(() => setReady(true)); }, []);
  if (!ready) return null;
  if (!user) return <Login onDone={setUser} />;
  const tabs = [{ id: "ask", label: "Ask" }, { id: "docs", label: "Documents" }, { id: "agents", label: "Agents" },
    ...(user.role === "admin" ? [{ id: "admin", label: "Admin" }] : [])];
  const initials = user.name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <>
      <div className="shell">
        <header className="glass topbar">
          <div className="brand">Sovereign AI</div>
          <div className="top-right">
            <ThemeButton />
            <div className="who"><span className="avatar">{initials}</span><div><b>{user.name}</b><small>{user.role}</small></div></div>
            <button className="btn soft small" onClick={() => api.logout().then(() => setUser(null))}>Sign out</button>
          </div>
        </header>
        <div className="page-head"><h1>{HEADS[tab][0]}</h1><p>{HEADS[tab][1]}</p></div>
        {tab === "ask" && <Ask />}
        {tab === "docs" && <Documents canEdit={user.role !== "viewer"} />}
        {tab === "agents" && <Agents />}
        {tab === "admin" && <Admin me={user} />}
      </div>
      <Dock tabs={tabs} tab={tab} setTab={setTab} />
    </>
  );
}
