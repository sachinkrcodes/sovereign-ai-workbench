import { useEffect, useState } from "react";
import * as api from "./api.js";

export function Agents() {
  const [list, setList] = useState([]);
  const [name, setName] = useState("researcher");
  const [task, setTask] = useState("");
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.agents().then(setList).catch((e) => setError(e.message)); }, []);
  const agent = list.find((a) => a.name === name);
  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(""); setRun(null);
    try { setRun(await api.runAgent(name, task.trim())); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return (
    <>
      <form className="glass ask" onSubmit={submit}>
        <select value={name} onChange={(e) => setName(e.target.value)} aria-label="Agent">
          {list.map((a) => <option key={a.name} value={a.name}>{a.title}</option>)}
        </select>
        {agent && <p className="muted">{agent.description} Allowed tools: {agent.allowed_tools.join(", ")}.</p>}
        <textarea rows={3} value={task} onChange={(e) => setTask(e.target.value)} placeholder="Describe the task, for example: compare the two safety manuals" aria-label="Task" />
        <button className="primary" disabled={busy || task.trim().length < 3}>{busy ? "Working…" : "Run agent"}</button>
      </form>
      {busy && <p className="muted pad">Agents call the model several times. This can take a few minutes.</p>}
      {error && <p className="error pad" role="alert">{error}</p>}
      {run && (
        <section className="glass answer">
          <p className="answer-text">{run.answer || run.error}</p>
          <ul className="sources">
            {run.steps.map((s) => (
              <li key={s.step} className={s.status === "denied" ? "denied" : ""}>
                <strong>Step {s.step}: {s.tool} ({s.status})</strong><span>{s.output_preview}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

export function Admin() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([api.usageSummary(), api.auditVerify(), api.auditList(), api.users()])
      .then(([usage, verify, audit, users]) => setData({ usage, verify, audit, users }))
      .catch((e) => setError(e.message));
  }, []);
  if (error) return <p className="error pad" role="alert">{error}</p>;
  if (!data) return <p className="muted pad">Loading…</p>;
  const { usage, verify, audit, users } = data;
  return (
    <>
      <section className="glass answer">
        <ul className="stats">
          <li><b>{usage.requests}</b><span>AI requests (7 days)</span></li>
          <li><b>{usage.total_tokens.toLocaleString()}</b><span>tokens used</span></li>
          <li><b>${usage.actual_cost_usd.toFixed(2)}</b><span>real cost (runs locally)</span></li>
          <li><b>${usage.equivalent_cloud_cost_usd.toFixed(4)}</b><span>equivalent hosted-API cost</span></li>
        </ul>
        <p className={verify.valid ? "ok" : "bad"} role="status">
          {verify.valid ? `Audit log intact: ${verify.events_checked} events verified.` : `Audit log was changed at event ${verify.first_invalid_id}.`}
        </p>
      </section>
      <section className="glass list">
        <h2>Recent activity</h2>
        {audit.items.map((e) => (
          <div className="row" key={e.id}>
            <strong>{e.action}</strong><small>{e.user_email || "anonymous"}</small>
            <span className={e.status === "success" ? "ok" : "bad"}>{e.status}</span>
          </div>
        ))}
      </section>
      <section className="glass list">
        <h2>Users</h2>
        {users.map((u) => (
          <div className="row" key={u.id}>
            <strong>{u.name}</strong><small>{u.email}</small><span>{u.role}{u.is_active ? "" : " (disabled)"}</span>
          </div>
        ))}
      </section>
    </>
  );
}
