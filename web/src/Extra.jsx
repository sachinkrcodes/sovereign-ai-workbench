import { useEffect, useState } from "react";
import * as api from "./api.js";
import { toast, useElapsed } from "./ui.jsx";

const stepChip = { ok: "chip good", denied: "chip bad", error: "chip warn" };
const when = (ts) => ts.replace("T", " ").slice(0, 19);

export function Agents() {
  const [list, setList] = useState([]);
  const [name, setName] = useState("researcher");
  const [task, setTask] = useState("");
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const secs = useElapsed(busy);
  useEffect(() => { api.agents().then(setList).catch((e) => toast(e.message, true)); }, []);
  const agent = list.find((a) => a.name === name);
  async function submit(e) {
    e.preventDefault();
    setBusy(true); setRun(null);
    try { setRun(await api.runAgent(name, task.trim())); }
    catch (err) { toast(err.message, true); }
    finally { setBusy(false); }
  }
  return (
    <div className="stack">
      <form className="glass panel" onSubmit={submit}>
        <div className="field"><label htmlFor="ag">Agent</label>
          <select id="ag" value={name} onChange={(e) => setName(e.target.value)}>{list.map((a) => <option key={a.name} value={a.name}>{a.title}</option>)}</select>
          {agent && <p className="hint">{agent.description} Allowed tools: {agent.allowed_tools.join(", ")}.</p>}</div>
        <div className="field"><label htmlFor="tk">Task</label>
          <textarea id="tk" value={task} onChange={(e) => setTask(e.target.value)} placeholder="For example: what did the trainee do at Reliance?" /></div>
        <button className="btn wide" disabled={busy || task.trim().length < 3}>{busy ? `Working… ${secs}s` : "Run agent"}</button>
        {busy && <p className="hint">Agents call the model several times, so expect 30 to 90 seconds.</p>}
      </form>
      {run && (
        <section className="glass panel">
          <p className="answer-text">{run.answer || run.error}</p>
          {run.notice && <div className="notice"><span className="chip warn">Check this</span><span className="sub">{run.notice}</span></div>}
          <div className="list">
            {run.steps.map((s) => (
              <div className="row wrap" key={s.step}>
                <span className="mini">{s.step}</span>
                <div className="grow"><b>{s.tool}</b><small>{s.output_preview}</small></div>
                <span className={stepChip[s.status] || "chip none"}>{s.status === "denied" ? <span>denied</span> : s.status}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export function Admin() {
  const [data, setData] = useState(null);
  useEffect(() => {
    Promise.all([api.usageSummary(), api.auditVerify(), api.auditList(), api.users()])
      .then(([usage, verify, audit, users]) => setData({ usage, verify, audit, users }))
      .catch((e) => toast(e.message, true));
  }, []);
  if (!data) return <div className="loading"><div className="sk" /><div className="sk tall" /></div>;
  const { usage, verify, audit, users } = data;
  return (
    <div className="stack">
      <section className="glass panel">
        <div className="stats">
          <div className="stat"><b>{usage.requests}</b><span>AI requests, 7 days</span></div>
          <div className="stat"><b>{usage.total_tokens.toLocaleString()}</b><span>tokens used</span></div>
          <div className="stat"><b>${usage.actual_cost_usd.toFixed(2)}</b><span>real cost (runs locally)</span></div>
          <div className="stat"><b>${usage.equivalent_cloud_cost_usd.toFixed(4)}</b><span>equivalent hosted-API cost</span></div>
        </div>
        <div className="notice">
          <span className={verify.valid ? "chip good" : "chip bad"}>{verify.valid ? "Log intact" : <span>Log changed</span>}</span>
          <span className="sub">{verify.valid ? `${verify.events_checked} events verified.` : `First changed event: ${verify.first_invalid_id}.`}</span>
        </div>
      </section>
      <div className="grid cols-2">
        <section className="glass panel"><h2>Recent activity</h2>
          <div className="list">{audit.items.map((e) => (
            <div className="row wrap" key={e.id}>
              <div className="grow"><b>{e.action}</b><small>{e.user_email || "anonymous"} · {when(e.ts)}</small></div>
              <span className={e.status === "success" ? "chip good" : "chip bad"}>{e.status === "success" ? e.status : <span>{e.status}</span>}</span>
            </div>))}</div></section>
        <section className="glass panel"><h2>People</h2>
          <div className="list">{users.map((u) => (
            <div className="row" key={u.id}><span className="avatar">{u.name.slice(0, 2).toUpperCase()}</span>
              <div className="grow"><b>{u.name}</b><small>{u.email}</small></div>
              <span className={u.is_active ? "chip none" : "chip bad"}>{u.is_active ? u.role : <span>disabled</span>}</span></div>))}</div></section>
      </div>
    </div>
  );
}
