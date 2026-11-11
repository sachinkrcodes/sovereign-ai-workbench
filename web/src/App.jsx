import { useEffect, useState } from "react";
import * as api from "./api.js";
import { Agents, Admin } from "./Extra.jsx";

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
    <main className="center">
      <form className="glass login" onSubmit={submit}>
        <h1>Sovereign AI Workbench</h1>
        <p className="muted">Ask questions about your company documents. Everything runs on your own machine.</p>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}

function Answer({ result }) {
  const { answer, sources, citations, notice, mode } = result;
  const cited = new Set(citations);
  return (
    <section className="glass answer" aria-live="polite">
      {answer ? <p className="answer-text">{answer}</p> : <p className="muted">The AI engine is unavailable, so here are the best matching passages.</p>}
      {notice && <p className="notice">{notice}</p>}
      {sources.length > 0 && (
        <ul className="sources">
          {sources.map((s) => (
            <li key={s.ref} className={cited.has(s.ref) ? "cited" : ""}>
              <strong>[{s.ref}] {s.filename}{s.page_number ? `, page ${s.page_number}` : ""}</strong>
              <span>{s.text.length > 260 ? s.text.slice(0, 260) + "…" : s.text}</span>
            </li>
          ))}
        </ul>
      )}
      {mode === "no_results" && <p className="muted">Upload a document on the Documents tab, then index it.</p>}
    </section>
  );
}

function Ask() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true); setError(""); setResult(null);
    try { setResult(await api.ask(query.trim())); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return (
    <>
      <form className="glass ask" onSubmit={submit}>
        <textarea rows={3} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="What does the shutdown procedure say about valve isolation?" aria-label="Your question" />
        <button className="primary" disabled={busy}>{busy ? "Thinking…" : "Ask"}</button>
      </form>
      {busy && <p className="muted pad">Reading your documents. The first answer can take a minute.</p>}
      {error && <p className="error pad" role="alert">{error}</p>}
      {result && <Answer result={result} />}
    </>
  );
}

function Documents({ canEdit }) {
  const [docs, setDocs] = useState([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api.listDocuments().then((d) => setDocs(d.items)).catch((e) => setMessage(e.message));
  useEffect(() => { load(); }, []);
  async function run(task, done) {
    setBusy(true); setMessage("");
    try { await task(); setMessage(done); await load(); }
    catch (e) { setMessage(e.message); }
    finally { setBusy(false); }
  }
  return (
    <>
      {canEdit && (
        <section className="glass tools">
          <label className="file">Upload a document
            <input type="file" accept=".pdf,.docx,.txt,.md" disabled={busy}
              onChange={(e) => e.target.files[0] && run(() => api.uploadDocument(e.target.files[0]), "Uploaded. Now index it so it can be searched.")} />
          </label>
          <button disabled={busy} onClick={() => run(api.indexAll, "Indexing finished.")}>{busy ? "Working…" : "Index new documents"}</button>
        </section>
      )}
      {message && <p className="notice pad" role="status">{message}</p>}
      <section className="glass list">
        {docs.length === 0 ? <p className="muted">No documents yet.</p> : (
          <ul>{docs.map((d) => (
            <li key={d.id}><strong>{d.filename}</strong><span>{d.page_count ? `${d.page_count} pages, ` : ""}{d.chunk_count} passages</span></li>
          ))}</ul>
        )}
      </section>
    </>
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(!api.getToken());
  const [tab, setTab] = useState("ask");
  useEffect(() => { if (api.getToken()) api.me().then(setUser).catch(() => {}).finally(() => setReady(true)); }, []);
  if (!ready) return null;
  if (!user) return <Login onDone={setUser} />;
  return (
    <main className="shell">
      <header className="glass bar">
        <strong className="brand">Sovereign AI</strong>
        <nav aria-label="Sections">
          <button className={tab === "ask" ? "tab on" : "tab"} onClick={() => setTab("ask")}>Ask</button>
          <button className={tab === "docs" ? "tab on" : "tab"} onClick={() => setTab("docs")}>Documents</button>
          <button className={tab === "agents" ? "tab on" : "tab"} onClick={() => setTab("agents")}>Agents</button>
          {user.role === "admin" && <button className={tab === "admin" ? "tab on" : "tab"} onClick={() => setTab("admin")}>Admin</button>}
        </nav>
        <span className="who">{user.name} ({user.role})</span>
        <button className="ghost" onClick={() => api.logout().then(() => setUser(null))}>Sign out</button>
      </header>
      {tab === "ask" && <Ask />}
      {tab === "docs" && <Documents canEdit={user.role !== "viewer"} />}
      {tab === "agents" && <Agents />}
      {tab === "admin" && <Admin />}
    </main>
  );
}
