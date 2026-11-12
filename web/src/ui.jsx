import { useEffect, useLayoutEffect, useRef, useState } from "react";

export function useElapsed(busy) {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    if (!busy) { setSecs(0); return undefined; }
    const id = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [busy]);
  return secs;
}

export function toast(msg, isErr) {
  let box = document.getElementById("toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), isErr ? 5000 : 2800);
}

export function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("theme", t); } catch { /* ignore */ }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = t === "dark" ? "#1A2B3C" : "#F7FAFC";
}
export function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch { /* ignore */ }
  applyTheme(saved || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
}
export function ThemeButton() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "light");
  const flip = () => { const next = theme === "dark" ? "light" : "dark"; applyTheme(next); setTheme(next); };
  return <button className="icon-btn" type="button" aria-label="Switch theme" onClick={flip}>{theme === "dark" ? "☀" : "☾"}</button>;
}

const ICONS = {
  ask: "M4 5h16v11H9l-5 4z",
  docs: "M6 3h8l4 4v14H6z M14 3v5h5",
  agents: "M12 3v3 M5 9h14v10H5z M9 13h.01 M15 13h.01",
  admin: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
};

export function Dock({ tabs, tab, setTab }) {
  const ref = useRef(null);
  const place = () => {
    const nav = ref.current;
    const link = nav && nav.querySelector('a[aria-current="page"]');
    const liquid = nav && nav.querySelector(".dock-liquid");
    if (!link || !liquid) return;
    const base = liquid.getBoundingClientRect();
    const box = link.getBoundingClientRect();
    ["lead", "trail"].forEach((name) => {
      const el = liquid.querySelector("." + name);
      el.style.width = box.width + "px";
      el.style.transform = `translateX(${box.left - base.left}px)`;
    });
  };
  useLayoutEffect(place, [tab, tabs.length]);
  useEffect(() => {
    addEventListener("resize", place);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(place);
    return () => removeEventListener("resize", place);
  }, []);
  return (
    <nav className="glass dock" aria-label="Main" ref={ref}>
      <div className="dock-liquid" aria-hidden="true"><i className="trail" /><i className="lead" /></div>
      {tabs.map((t) => (
        <a key={t.id} href={`#${t.id}`} aria-current={t.id === tab ? "page" : undefined}
           onClick={(e) => { e.preventDefault(); setTab(t.id); }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d={ICONS[t.id]} /></svg>
          <span>{t.label}</span>
        </a>
      ))}
    </nav>
  );
}
