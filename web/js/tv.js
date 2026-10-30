"use strict";
/* Klangstation – „Läuft gerade“-Bildschirm. Liest nur den Zustand über den WebSocket. */
const $ = (s) => document.querySelector(s);
const KIND = { file: "Bibliothek", radio: "Webradio", cd: "Audio-CD", spotify: "Spotify Connect", airplay: "AirPlay",
  upnp: "UPnP/DLNA", bluetooth: "Bluetooth" };

let S = null, receivedAt = 0, lastArt = null, webBuild = null;
// Liedtext zum aktuellen Titel: {key, data} - data null = (noch) keiner
let lyr = { key: null, data: null, line: -1 };

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}

function audioFormat(n) {
  const parts = [];
  if (n.format) {
    const [rate, bits, ch] = n.format.split(":");
    if (rate && rate !== "*") parts.push((rate / 1000).toLocaleString("de-DE") + " kHz");
    if (bits && bits !== "*" && bits !== "f") parts.push(bits + " bit");
    if (ch) parts.push(ch === "2" ? "Stereo" : ch === "1" ? "Mono" : ch + " Kanäle");
  }
  if (n.bitrate && n.bitrate !== "0") parts.push(n.bitrate + " kbit/s");
  return parts.join(" · ");
}

function setArt(url) {
  if (url === lastArt) return;
  lastArt = url;
  const img = $("#art"), fb = $("#art-fallback");
  if (!url) { img.hidden = true; fb.hidden = false; return; }
  img.onload = () => { img.hidden = false; fb.hidden = true; };
  img.onerror = () => { img.hidden = true; fb.hidden = false; };
  img.referrerPolicy = "no-referrer";
  img.src = url;
}

function elapsedNow() {
  const n = (S && S.now) || {};
  let e = n.elapsed || 0;
  if (n.state === "play") e += (performance.now() - receivedAt) / 1000;
  return n.duration ? Math.min(e, n.duration) : e;
}

function render() {
  if (!S) return;
  const n = S.now || {};
  $("#device").textContent = S.device_name || "";
  document.documentElement.dataset.theme = S.tv_theme || "classic";
  // „Läuft gerade“ bei Wiedergabe und kurz pausiert; sonst Bildschirmschoner
  const active = n.kind && (n.state === "play" || n.state === "pause") && (n.title || n.artist);
  $("#playing").hidden = !active;
  $("#idle").hidden = !!active;
  sleepTick();
  if (!active) { renderIdle(); return; }
  $("#playing").classList.toggle("paused", n.state === "pause");
  $("#badge").textContent = (S.timers && S.timers.ringing ? "Wecker · " : "") + (KIND[n.kind] || "") + (n.extra ? " · " + n.extra : "") + (n.state === "pause" ? " · Pause" : "");
  $("#title").textContent = n.title || "";
  $("#artist").textContent = n.artist || "";
  $("#album").textContent = n.album || "";
  $("#format").textContent = audioFormat(n);
  setArt(n.art || null);
  loadLyrics(n);
  tick();
}

function tick() {
  const n = (S && S.now) || {};
  const e = elapsedNow();
  $("#progress").hidden = !n.duration && n.kind !== "radio";
  $("#elapsed").textContent = fmt(e);
  $("#total").textContent = n.duration ? fmt(n.duration) : n.kind === "radio" ? "Live" : "";
  $("#fill").style.width = n.duration ? Math.min(100, (e / n.duration) * 100) + "%" : n.kind === "radio" ? "100%" : "0";
}

/* ---------------------------------------------------------- Liedtexte */
function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// Instrumental-Pausen wie bei Spotify als Notenzeile: im Vorspiel, an leeren Zeilen und in langen Luecken
const NOTE_MIN = 5;  // kuerzere Pausen bleiben eine Leerzeile
function withBreaks(lines) {
  const out = [];
  if (lines.length && lines[0].t >= NOTE_MIN) out.push({ t: 0, end: lines[0].t, note: true });
  lines.forEach((l, i) => {
    const next = lines[i + 1];
    if (!l.text) {
      if (next && next.t - l.t >= NOTE_MIN) out.push({ t: l.t, end: next.t, note: true });
      else if (next) out.push({ t: l.t, text: "" });
      return;
    }
    out.push(l);
    // Ohne Leerzeile in der LRC: nach der (geschaetzten) Singdauer der Zeile Noten bis zur naechsten
    if (next && next.text) {
      const sung = Math.min(7, Math.max(3, l.text.length * 0.3));
      if (next.t - (l.t + sung) >= NOTE_MIN + 3) out.push({ t: l.t + sung, end: next.t, note: true });
    }
  });
  return out;
}

function showLyrics(data) {
  if (data && data.kind === "synced") data = Object.assign({}, data, { lines: withBreaks(data.lines) });
  lyr.data = data; lyr.line = -1;
  const box = $("#lyrics"), inner = $("#lyrics-inner");
  $("#playing").classList.toggle("with-lyrics", !!data);
  box.hidden = !data;
  inner.style.transform = "translateY(0)";
  inner.classList.toggle("plain-mode", !!data && data.kind !== "synced");
  if (!data) { inner.innerHTML = ""; return; }
  const src = data.source ? `<div class="source">Text: ${esc(data.source)}</div>` : "";
  inner.innerHTML = data.kind === "synced"
    ? data.lines.map((l, i) => l.note
        ? `<div class="line note" data-i="${i}"><span>♪</span><span>♪</span><span>♪</span></div>`
        : `<div class="line${l.text ? "" : " gap"}" data-i="${i}">${esc(l.text)}</div>`).join("") + src
    : `<div class="plain">${esc(data.text)}</div>` + src;
  lyricsTick();
}

function loadLyrics(n) {
  // Webradio: keine Laenge, Titel oft ungenau - der Text liefe nicht mit
  const want = S.tv_lyrics && n.kind !== "radio" && n.title && (n.artist || n.uri);
  // Laenge nur als "bekannt/unbekannt" im Schluessel: AirPlay meldet sie oft erst nach dem Titel
  const key = want ? [n.kind, n.uri || "", n.artist, n.title, n.album, n.duration > 0].join("|") : null;
  if (key === lyr.key) return;
  lyr.key = key;
  showLyrics(null);
  if (!key) return;
  const q = new URLSearchParams({ artist: n.artist || "", title: n.title, album: n.album || "",
    duration: String(Math.round(n.duration || 0)) });
  if (n.kind === "file" && n.uri) q.set("uri", n.uri);
  fetch("/api/lyrics?" + q).then((r) => (r.ok ? r.json() : null)).catch(() => null).then((data) => {
    if (lyr.key !== key) return;  // inzwischen anderer Titel
    if (data && data.kind === "instrumental") data = null;
    showLyrics(data);
  });
}

function lyricsTick() {
  const d = lyr.data;
  if (!d || $("#lyrics").hidden) return;
  const box = $("#lyrics"), inner = $("#lyrics-inner");
  const e = elapsedNow();
  if (d.kind === "synced") {
    // Zeile etwas frueher hervorheben, damit sie beim Singen schon steht
    let i = -1;
    for (let k = 0; k < d.lines.length && d.lines[k].t <= e + 0.3; k++) i = k;
    const cur = d.lines[i];
    if (cur && cur.note) {
      // Noten leuchten nacheinander auf, bis die naechste Zeile kommt
      const lit = Math.min(3, 1 + Math.floor(((e - cur.t) / Math.max(1, cur.end - cur.t)) * 3));
      inner.querySelectorAll(`[data-i="${i}"] span`).forEach((s, k) => s.classList.toggle("on", k < lit));
    }
    if (i === lyr.line) return;
    const old = inner.querySelector(".line.now");
    if (old) old.classList.remove("now");
    lyr.line = i;
    const el = i >= 0 ? inner.querySelector(`[data-i="${i}"]`) : null;
    if (el) el.classList.add("now");
    const y = el ? el.offsetTop - box.clientHeight * 0.35 : 0;
    inner.style.transform = `translateY(${-Math.round(y)}px)`;
  } else {
    const n = S.now || {};
    const frac = n.duration ? Math.min(1, e / n.duration) : 0;
    const max = Math.max(0, inner.scrollHeight - box.clientHeight * 0.7);
    inner.style.transform = `translateY(${-Math.round(max * frac)}px)`;
  }
}

/* ---------------------------------------------------------- Ruhezustand */
let recentKey = null;
function renderIdle() {
  const w = S.weather, we = $("#idle-weather");
  we.hidden = !w;
  if (w) we.innerHTML = w.error ? esc(w.error)
    : `<span class="sym">${esc(w.symbol)}</span>${w.temp}° ${esc(w.text)}<small>↑ ${w.max}° ↓ ${w.min}° · ${esc(w.place)}</small>`;
  const na = S.timers && S.timers.next_alarm, al = $("#idle-alarm");
  al.hidden = !na;
  if (na) al.textContent = `Wecker ${alarmDay(na)} ${na.time} · ${na.label}`;
  const hist = S.history || [];
  const key = hist.map((h) => h.art + h.title).join("|") + "@" + window.innerWidth;
  if (key === recentKey) return;
  recentKey = key;
  $("#recent").hidden = !hist.length;
  if (!hist.length) return;
  // Genug Kopien, dass eine Haelfte breiter ist als der Bildschirm: dann laeuft das Band nahtlos durch
  const itemPx = window.innerHeight * 0.20;
  const reps = Math.max(1, Math.ceil(window.innerWidth / (hist.length * itemPx)));
  // Ohne Cover (Datei ohne Bild) das Notensymbol wie auf dem Wiedergabe-Bildschirm
  const one = hist.map((h) => `<div class="recent-item"><img src="${esc(h.art)}" alt="" referrerpolicy="no-referrer"
    onerror="this.replaceWith(Object.assign(document.createElement('b'), {className: 'recent-fb', textContent: '♪'}))">
    <div>${esc(h.title)}</div></div>`).join("");
  const track = $("#recent-track");
  track.innerHTML = one.repeat(reps * 2);
  track.style.setProperty("--dur", hist.length * reps * 10 + "s");
}

function alarmDay(na) {
  const d = new Date(na.at * 1000), today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  if (d.toDateString() === today.toDateString()) return "heute";
  if (d.toDateString() === tomorrow.toDateString()) return "morgen";
  return na.day;
}

function sleepTick() {
  const sl = S && S.timers && S.timers.sleep, el = $("#sleep");
  el.hidden = !sl;
  if (!sl) return;
  const left = sl.until - S.timers.ts - (performance.now() - receivedAt) / 1000;
  el.textContent = "☾ " + (sl.mode === "track" ? "nach diesem Titel" : fmt(Math.max(0, left)));
}

function clock() {
  const d = new Date();
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  $("#clock").textContent = time;
  $("#idle-time").textContent = time;
  $("#idle-date").textContent = d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" });
  sleepTick();
  // Ragt die Uhr (z. B. nach dem Einblenden von Band, Wetter oder Wecker) ueber den Rand oder ins Coverband,
  // woanders hin damit. Ziel statt aktueller Position pruefen - waehrend des Gleitens laege sie sonst kurz "falsch"
  const box = $("#idle-box"), recent = $("#recent");
  if (!$("#idle").hidden) {
    const bottom = recent.hidden ? window.innerHeight : recent.getBoundingClientRect().top;
    if (parseFloat(box.style.left || 0) + box.offsetWidth > window.innerWidth ||
        parseFloat(box.style.top || 0) + box.offsetHeight > bottom) moveIdle();
  }
}

// Bildschirmschoner: Uhr jede Minute an eine andere Stelle, damit nichts einbrennt
function moveIdle() {
  const box = $("#idle-box");
  const w = window.innerWidth, h = window.innerHeight;
  const bw = box.offsetWidth || 400, bh = box.offsetHeight || 200;
  const recent = $("#recent");
  // Unten Platz fuer das Coverband lassen
  const bottom = recent.hidden || $("#idle").hidden ? h * 0.88 : recent.getBoundingClientRect().top - h * 0.03;
  box.style.left = Math.round(Math.random() * Math.max(0, w - bw)) + "px";
  box.style.top = Math.round(h * 0.10 + Math.random() * Math.max(0, bottom - h * 0.10 - bh)) + "px";
}

function connect() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") {
      // Nach einem Update liefert Klangstation neue Oberflaechen-Dateien: der Kiosk-Browser laedt sonst nie neu
      if (webBuild && msg.data.web_build && msg.data.web_build !== webBuild) { location.reload(); return; }
      webBuild = webBuild || msg.data.web_build;
      S = msg.data; receivedAt = performance.now(); render();
    }
  };
  ws.onclose = (ev) => {
    $("#idle-hint").textContent = ev.code === 4401
      ? "Anmeldung nötig – bitte Klangstation im Browser öffnen und anmelden"
      : "Verbindung zur Klangstation wird hergestellt …";
    $("#playing").hidden = true; $("#idle").hidden = false;
    setTimeout(connect, ev.code === 4401 ? 15000 : 2000);
  };
  ws.onopen = () => { $("#idle-hint").textContent = ""; };
}

/* Dezenter Hintergrund: langsam treibende Leuchtbänder, nur bei Wiedergabe lebhafter */
const bg = $("#bg");
let level = 0;
function draw(t) {
  requestAnimationFrame(draw);
  const w = bg.clientWidth, h = bg.clientHeight;
  if (bg.width !== w || bg.height !== h) { bg.width = w; bg.height = h; }
  const g = bg.getContext("2d");
  const playing = S && S.now && S.now.state === "play";
  level += ((playing ? 1 : 0.25) - level) * 0.02;
  const s = t / 1000;
  g.clearRect(0, 0, w, h);
  const aero = document.documentElement.dataset.theme === "aero";
  if (aero) drawBubbles(g, w, h, s);
  g.globalCompositeOperation = "lighter";
  for (let k = 0; k < 3; k++) {
    g.beginPath();
    for (let x = 0; x <= w; x += 12) {
      const y = h * (0.62 + k * 0.08) + Math.sin(x / (180 + k * 60) + s * (0.25 + k * 0.1)) * h * 0.06 * level
        + Math.sin(x / 90 + s * 0.6 + k) * h * 0.015 * level;
      x === 0 ? g.moveTo(x, y) : g.lineTo(x, y);
    }
    g.strokeStyle = (aero ? ["rgba(255,255,255,.35)", "rgba(150,235,255,.3)", "rgba(150,220,100,.28)"]
      : ["rgba(111,211,255,.35)", "rgba(80,120,255,.28)", "rgba(180,90,255,.22)"])[k];
    g.lineWidth = 2 + level * 3;
    g.stroke();
  }
  g.globalCompositeOperation = "source-over";
}

/* Aero: Luftblasen steigen langsam auf - ruhig genug fuer den Fernseher, nichts steht still */
const bubbles = Array.from({ length: 18 }, (_, i) => ({
  x: Math.random(), r: 0.012 + Math.random() * 0.035, speed: 0.008 + Math.random() * 0.018,
  phase: Math.random() * 6.28, y0: Math.random(),
}));
function drawBubbles(g, w, h, s) {
  const u = Math.min(w, h);
  for (const b of bubbles) {
    const y = (1.1 - ((b.y0 + s * b.speed * (0.5 + level)) % 1.2)) * h;
    const x = (b.x + Math.sin(s * 0.3 + b.phase) * 0.02) * w, r = b.r * u;
    const grad = g.createRadialGradient(x - r * 0.35, y - r * 0.4, r * 0.05, x, y, r);
    grad.addColorStop(0, "rgba(255,255,255,.75)");
    grad.addColorStop(0.25, "rgba(255,255,255,.08)");
    grad.addColorStop(0.85, "rgba(255,255,255,.12)");
    grad.addColorStop(1, "rgba(255,255,255,.55)");
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2);
    g.fillStyle = grad; g.fill();
  }
}

clock();
setInterval(clock, 1000);
setInterval(tick, 500);
setInterval(lyricsTick, 200);
moveIdle();
setInterval(moveIdle, 60000);
requestAnimationFrame(draw);
connect();
