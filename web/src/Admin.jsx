import { useEffect, useState } from "react";
import * as api from "./api.js";
import { toast } from "./ui.jsx";

const when = (ts) => ts.replace("T", " ").slice(0, 19);
const ROLES = ["viewer", "analyst", "admin"];
const ACTIONS = ["auth.login", "auth.setup", "auth.logout", "document.upload", "document.delete", "index.run", "qa.ask", "qa.search",
  "agent.run", "user.create", "user.update", "access.denied", "usage.limit_reached"];
const clip = (t, n = 90) => (t.length > n ? t.slice(0, n) + "…" : t);

function Overview() {
  const [data, setData] = useState(null);
  useEffect(() => {
    Promise.all([api.usageSummary(), api.auditVerify()]).then(([usage, verify]) => setData({ usage, verify })).catch((e) => toast(e.message, true));
  }, []);
  if (!data) return <div className="loading"><div className="sk" /><div className="sk tall" /></div>;
  const { usage, verify } = data;
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
        <section className="glass panel"><h2>Usage by person</h2>
          <div className="list">{usage.by_user.length === 0 ? <p className="sub">No AI usage yet.</p> : usage.by_user.map((u) => (
            <div className="row" key={u.email}><div className="grow"><b>{u.email}</b><small>{u.requests} requests</small></div><span className="chip none">{u.total_tokens.toLocaleString()} tokens</span></div>))}</div></section>
        <section className="glass panel"><h2>Usage by day</h2>
          <div className="list">{usage.by_day.length === 0 ? <p className="sub">Nothing yet.</p> : usage.by_day.map((d) => (
            <div className="row" key={d.day}><div className="grow"><b>{d.day}</b><small>{d.requests} requests</small></div><span className="chip none">{d.total_tokens.toLocaleString()} tokens</span></div>))}</div></section>
      </div>
    </div>
  );
}

function People({ me }) {
  const blank = { name: "", email: "", password: "", role: "viewer" };
  const [users, setUsers] = useState(null);
  const [form, setForm] = useState(blank);
  const load = () => api.users().then(setUsers).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);
  const change = async (id, body, msg) => {
    try { await api.updateUser(id, body); toast(msg); load(); } catch (e) { toast(e.message, true); }
  };
  async function create(e) {
    e.preventDefault();
    try { await api.createUser(form); toast("Person added."); setForm(blank); load(); } catch (err) { toast(err.message, true); }
  }
  const reset = (u) => {
    const pw = window.prompt(`New password for ${u.email} (at least 8 characters):`);
    if (pw) change(u.id, { password: pw }, "Password changed. They were signed out.");
  };
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  return (
    <div className="stack">
      <form className="glass panel" onSubmit={create}>
        <h2>Add a person</h2>
        <div className="form-row">
          <div className="field"><label htmlFor="un">Name</label><input id="un" type="text" value={form.name} onChange={set("name")} required /></div>
          <div className="field"><label htmlFor="ue">Email</label><input id="ue" type="email" value={form.email} onChange={set("email")} required /></div>
          <div className="field"><label htmlFor="up">Password</label><input id="up" type="password" minLength={8} value={form.password} onChange={set("password")} required /></div>
          <div className="field"><label htmlFor="ur">Role</label><select id="ur" value={form.role} onChange={set("role")}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></div>
          <button className="btn">Add</button>
        </div>
        <p className="hint">Viewer: read and ask. Analyst: also upload documents and run agents. Admin: everything, including this page.</p>
      </form>
      <section className="glass panel"><h2>People</h2>
        {!users ? <div className="loading"><div className="sk short" /></div> : (
          <div className="list">{users.map((u) => (
            <div className="row wrap" key={u.id}>
              <span className="avatar">{u.name.slice(0, 2).toUpperCase()}</span>
              <div className="grow"><b>{u.name}{u.id === me.id ? " (you)" : ""}</b><small>{u.email}</small></div>
              <select aria-label={`Role of ${u.email}`} value={u.role} disabled={u.id === me.id} style={{ width: "auto", minHeight: 40 }}
                onChange={(e) => change(u.id, { role: e.target.value }, "Role updated.")}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select>
              <span className={u.is_active ? "chip good" : "chip bad"}>{u.is_active ? "active" : <span>disabled</span>}</span>
              {u.id !== me.id && (
                <div className="actions">
                  <button className="btn soft small" onClick={() => reset(u)}>Reset password</button>
                  <button className="btn danger small" onClick={() => change(u.id, { is_active: !u.is_active }, u.is_active ? "Person disabled." : "Person enabled.")}>{u.is_active ? "Disable" : "Enable"}</button>
                </div>)}
            </div>))}</div>)}
      </section>
    </div>
  );
}

function Activity() {
  const [filters, setFilters] = useState({ action: "", status: "" });
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const fetchPage = (offset, replace) => {
    setLoading(true);
    api.auditList({ ...filters, limit: 20, offset })
      .then((r) => { setItems((cur) => (replace ? r.items : [...cur, ...r.items])); setTotal(r.total); })
      .catch((e) => toast(e.message, true)).finally(() => setLoading(false));
  };
  useEffect(() => { fetchPage(0, true); }, [filters]);
  return (
    <section className="glass panel">
      <div className="form-row">
        <div className="field"><label htmlFor="fa">Action</label>
          <select id="fa" value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })}><option value="">All actions</option>{ACTIONS.map((a) => <option key={a}>{a}</option>)}</select></div>
        <div className="field"><label htmlFor="fs">Result</label>
          <select id="fs" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">All results</option><option>success</option><option>failed</option><option>denied</option></select></div>
        <p className="sub">{total} events</p>
      </div>
      <div className="list">{items.map((e) => (
        <div className="row wrap" key={e.id}>
          <div className="grow"><b>{e.action}</b><small>{e.user_email || "anonymous"} · {when(e.ts)}{e.detail && Object.keys(e.detail).length ? ` · ${clip(JSON.stringify(e.detail))}` : ""}</small></div>
          <span className={e.status === "success" ? "chip good" : e.status === "denied" ? "chip bad" : "chip warn"}>{e.status === "denied" ? <span>denied</span> : e.status}</span>
        </div>))}</div>
      {items.length < total && <div className="actions" style={{ marginTop: 14 }}><button className="btn soft" disabled={loading} onClick={() => fetchPage(items.length, false)}>{loading ? "Loading…" : "Load more"}</button></div>}
    </section>
  );
}

function Runs() {
  const [runs, setRuns] = useState(null);
  useEffect(() => { api.runsList().then((r) => setRuns(r.items)).catch((e) => toast(e.message, true)); }, []);
  if (!runs) return <div className="loading"><div className="sk tall" /></div>;
  return (
    <section className="glass panel"><h2>Agent runs</h2>
      <p className="sub">Every task any agent has run, with the tools it used.</p>
      <div className="list">{runs.length === 0 ? <div className="empty"><h3>No runs yet</h3></div> : runs.map((r) => (
        <div className="row wrap" key={r.id}>
          <span className="mini">{r.agent.slice(0, 2).toUpperCase()}</span>
          <div className="grow"><b>{r.task}</b><small>{r.agent} · {r.steps.length} tool calls · {(r.duration_ms / 1000).toFixed(1)}s · {when(r.created_at)}</small></div>
          <span className={r.status === "completed" ? "chip good" : r.status === "failed" ? "chip bad" : "chip warn"}>{r.status === "failed" ? <span>failed</span> : r.status}</span>
        </div>))}</div>
    </section>
  );
}

export default function Admin({ me }) {
  const [tab, setTab] = useState("overview");
  const tabs = [["overview", "Overview"], ["people", "People"], ["activity", "Activity"], ["runs", "Agent runs"]];
  return (
    <>
      <div className="tabs four" role="tablist">
        {tabs.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>)}
      </div>
      {tab === "overview" && <Overview />}
      {tab === "people" && <People me={me} />}
      {tab === "activity" && <Activity />}
      {tab === "runs" && <Runs />}
    </>
  );
}
