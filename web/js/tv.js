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
  renderBattery();
  if (!active) { renderIdle(); return; }
  $("#playing").classList.toggle("paused", n.state === "pause");
  $("#badge").textContent = (S.timers && S.timers.ringing ? "Wecker · " : "") + (KIND[n.kind] || "") + (n.extra ? " · " + n.extra : "") + (n.state === "pause" ? " · Pause" : "");
  scrollText($("#title"), n.title || "");
  scrollText($("#artist"), n.artist || "");
  scrollText($("#album"), n.album || "");
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

/* Winamp: zu lange Texte laufen wie im Original durch (Text *** Text ..., nahtlos). Nur neu aufbauen, wenn sich
   Text, Theme oder Breite aendern - sonst finge die Laufschrift bei jedem neuen Zustand von vorn an.
   Gleicher Code in app.js. */
const scrollEls = new Set();
function scrollText(el, text) {
  scrollEls.add(el);
  const run = document.documentElement.dataset.theme === "winamp";
  const key = text + "|" + run + "|" + el.clientWidth;
  if (el._scrollKey === key) return;
  el._scrollKey = key;
  el._scrollText = text;
  el.textContent = text;
  if (!run || el.scrollWidth <= el.clientWidth + 1) return;
  el.innerHTML = `<span class="marquee"><span>${esc(text)}</span><span aria-hidden="true">${esc(text)}</span></span>`;
  // etwa zwei Schriftgroessen pro Sekunde: auf Handy und Fernseher gleich gut lesbar
  const speed = parseFloat(getComputedStyle(el).fontSize) * 2;
  el.firstChild.style.animationDuration = Math.max(5, el.firstChild.offsetWidth / 2 / speed) + "s";
}
function rescroll() { for (const el of scrollEls) scrollText(el, el._scrollText); }
addEventListener("resize", rescroll);

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
  rescroll();  // mit Liedtext ist der Titel kleiner
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

// Laptop: Akkusymbol mit Ladestand, Blitz bei angestecktem Netzteil
function renderBattery() {
  const b = S && S.battery, el = $("#battery");
  el.hidden = !b;
  if (!b) return;
  const key = b.percent + "/" + b.charging;
  if (el.dataset.key === key) return;
  el.dataset.key = key;
  const w = Math.round(b.percent / 100 * 17);
  el.classList.toggle("low", b.percent <= 15 && !b.charging);
  el.title = b.percent + " %" + (b.charging ? ", Netzteil angeschlossen" : "");
  el.innerHTML =
    '<svg viewBox="0 0 26 12" aria-hidden="true"><rect x=".75" y=".75" width="21" height="10.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/>' +
    '<rect x="23" y="3.5" width="2.25" height="5" rx="1" fill="currentColor"/>' +
    '<rect class="level" x="2.5" y="2.5" width="' + w + '" height="7" rx="1"/></svg>' +
    (b.charging ? '<svg class="bolt" viewBox="0 0 8 12" aria-hidden="true"><path d="M5 0 0 7h3l-1 5 6-7.5H5z" fill="currentColor"/></svg>' : "") +
    "<span>" + b.percent + " %</span>";
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

/* Dezenter Hintergrund: langsam treibende Leuchtbaender, nur bei Wiedergabe lebhafter.
   Je nach Theme stattdessen oder zusaetzlich: Blasen (Aero), Wolken (Luna), Spektrum (Winamp), VU-Meter (Hi-Fi) */
const WAVES = {
  classic: ["rgba(111,211,255,.35)", "rgba(80,120,255,.28)", "rgba(180,90,255,.22)"],
  aero: ["rgba(255,255,255,.35)", "rgba(150,235,255,.3)", "rgba(150,220,100,.28)"],
  nacht: ["rgba(127,152,176,.12)", "rgba(100,115,150,.1)", "rgba(120,105,150,.08)"],
  aqua: ["rgba(255,255,255,.16)", "rgba(180,200,230,.14)", "rgba(150,170,200,.12)"],
  luna: ["rgba(255,255,255,.28)", "rgba(160,210,255,.24)", "rgba(150,220,110,.2)"],
};
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
  const theme = document.documentElement.dataset.theme;
  if (theme === "winamp") { drawSpectrum(g, w, h, s); return; }
  if (theme === "hifi") { if (!$("#playing").hidden) drawMeters(g, w, h, s); return; }
  if (theme === "aero") drawBubbles(g, w, h, s);
  if (theme === "luna") drawClouds(g, w, h, s);
  const colors = WAVES[theme] || WAVES.classic;
  g.globalCompositeOperation = "lighter";
  for (let k = 0; k < 3; k++) {
    g.beginPath();
    for (let x = 0; x <= w; x += 12) {
      const y = h * (0.62 + k * 0.08) + Math.sin(x / (180 + k * 60) + s * (0.25 + k * 0.1)) * h * 0.06 * level
        + Math.sin(x / 90 + s * 0.6 + k) * h * 0.015 * level;
      x === 0 ? g.moveTo(x, y) : g.lineTo(x, y);
    }
    g.strokeStyle = colors[k];
    g.lineWidth = 2 + level * 3;
    g.stroke();
  }
  g.globalCompositeOperation = "source-over";
}

/* Winamp: Spektrum aus Leuchtsegmenten am unteren Rand, gruen-gelb-rot mit fallenden Spitzen */
const spec = { peaks: [] };
function drawSpectrum(g, w, h, s) {
  const n = 40, bw = w / n, seg = h * 0.011, maxH = h * 0.16;
  const beat = 0.6 + 0.4 * Math.pow(Math.max(0, Math.sin(s * 7.6)), 6);
  for (let i = 0; i < n; i++) {
    const x = i / n;
    const v = (0.55 * Math.abs(Math.sin(s * 1.7 + i * 0.45)) + 0.3 * Math.abs(Math.sin(s * 3.9 + i * 1.3)) +
      0.25 * Math.abs(Math.sin(s * 0.8 + i * 0.12))) * (1.1 - x * 0.55) * beat;
    const segs = Math.max(1, Math.round((v * maxH * level) / seg));
    for (let k = 0; k < segs; k++) {
      const f = (k * seg) / maxH;
      g.fillStyle = f > 0.85 ? "#e83a0f" : f > 0.6 ? "#d8c010" : "#18b818";
      g.fillRect(i * bw + bw * 0.12, h - (k + 1) * seg, bw * 0.76, seg * 0.7);
    }
    spec.peaks[i] = Math.max((spec.peaks[i] || 0) - 0.15, segs);
    g.fillStyle = "#b8b8c4";
    g.fillRect(i * bw + bw * 0.12, h - (Math.round(spec.peaks[i]) + 1) * seg, bw * 0.76, seg * 0.35);
  }
}

/* Hi-Fi: zwei VU-Meter unter Cover und Titel (Platz schafft tv-hifi.css) */
const vuVals = [0, 0];
function drawMeters(g, w, h, s) {
  const mh = Math.min(h * 0.19, w * 0.42 / 1.7), mw = mh * 1.7, gap = w * 0.04;
  const x0 = (w - 2 * mw - gap) / 2, y0 = h - mh - h * 0.035;
  vuLevels(vuVals, s, level > 0.5 ? level : 0);
  vuMeter(g, x0, y0, mw, mh, vuVals[0], "L");
  vuMeter(g, x0 + mw + gap, y0, mw, mh, vuVals[1], "R");
}

/* VU-Meter: gleicher Code in app.js */
function vuLevels(vu, s, L) {
  const beat = Math.pow(Math.max(0, Math.sin(s * 7.6)), 6);
  for (let ch = 0; ch < 2; ch++) {
    const target = L * (0.42 + 0.3 * Math.abs(Math.sin(s * 2.1 + ch) * Math.sin(s * 5.3 + ch * 2)) + 0.22 * beat
      + 0.06 * Math.sin(s * 13 + ch * 4));
    vu[ch] += (target - vu[ch]) * (target > vu[ch] ? 0.18 : 0.08);
  }
}
function vuMeter(g, x, y, w, h, v, label) {
  const dbFrac = (db) => (Math.pow(10, db / 20) - 0.1) / (Math.pow(10, 3 / 20) - 0.1);
  const cx = x + w / 2, cy = y + h * 1.18, r = h * 0.95, span = 0.85;
  const ang = (f) => -Math.PI / 2 - span + f * span * 2;
  g.save();
  g.beginPath(); g.roundRect(x, y, w, h, h * 0.06);
  const face = g.createLinearGradient(0, y, 0, y + h);
  face.addColorStop(0, "#f7e2ac"); face.addColorStop(1, "#e2b765");
  g.fillStyle = face; g.fill();
  g.lineWidth = Math.max(2, h * 0.03); g.strokeStyle = "#1e1b17"; g.stroke();
  g.clip();
  const glow = g.createRadialGradient(cx, y + h * 0.55, 0, cx, y + h * 0.55, w * 0.6);
  glow.addColorStop(0, "rgba(255,240,200,.55)"); glow.addColorStop(1, "rgba(255,240,200,0)");
  g.fillStyle = glow; g.fillRect(x, y, w, h);
  // Skala: schwarz bis 0 dB, rot darueber
  g.lineWidth = Math.max(1.5, h * 0.025);
  g.beginPath(); g.arc(cx, cy, r * 0.82, ang(0), ang(dbFrac(0))); g.strokeStyle = "#2a2117"; g.stroke();
  g.beginPath(); g.arc(cx, cy, r * 0.82, ang(dbFrac(0)), ang(1)); g.strokeStyle = "#c0281a"; g.lineWidth *= 2.2; g.stroke();
  g.font = `${Math.round(h * 0.1)}px sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
  for (const db of [-20, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3]) {
    const a = ang(dbFrac(db)), major = [-20, -10, -5, -3, 0, 3].includes(db);
    g.beginPath();
    g.moveTo(cx + Math.cos(a) * r * 0.82, cy + Math.sin(a) * r * 0.82);
    g.lineTo(cx + Math.cos(a) * r * (major ? 0.93 : 0.89), cy + Math.sin(a) * r * (major ? 0.93 : 0.89));
    g.strokeStyle = db > 0 ? "#c0281a" : "#2a2117"; g.lineWidth = Math.max(1, h * 0.015); g.stroke();
    if (major) {
      g.fillStyle = db > 0 ? "#c0281a" : "#2a2117";
      g.fillText(db > 0 ? "+" + db : String(db), cx + Math.cos(a) * r * 1.02, cy + Math.sin(a) * r * 1.02);
    }
  }
  g.font = `bold ${Math.round(h * 0.13)}px sans-serif`; g.fillStyle = "#2a2117";
  g.fillText("VU", cx, y + h * 0.62);
  g.font = `${Math.round(h * 0.09)}px sans-serif`;
  g.fillText(label, x + w * 0.1, y + h * 0.86);
  // Zeiger
  const a = ang(Math.max(0, Math.min(1.04, v)));
  g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.cos(a) * r * 0.97, cy + Math.sin(a) * r * 0.97);
  g.strokeStyle = "#111"; g.lineWidth = Math.max(1.5, h * 0.018); g.stroke();
  g.fillStyle = "#1e1b17"; g.fillRect(x, y + h * 0.9, w, h * 0.1);
  g.restore();
}

/* Luna: weiche Wolken ziehen langsam ueber den Himmel */
const clouds = Array.from({ length: 6 }, (_, i) => ({
  x: Math.random(), y: 0.08 + Math.random() * 0.35, r: 0.06 + Math.random() * 0.07, speed: 0.002 + Math.random() * 0.003,
}));
function drawClouds(g, w, h, s) {
  for (const c of clouds) {
    const x = (((c.x + s * c.speed) % 1.4) - 0.2) * w, y = c.y * h, r = c.r * w;
    for (const [dx, dy, k] of [[0, 0, 1], [-0.6, 0.15, 0.7], [0.6, 0.12, 0.75], [0.25, -0.25, 0.65]]) {
      const cx = x + dx * r, cy = y + dy * r, rr = r * k;
      const grad = g.createRadialGradient(cx, cy, 0, cx, cy, rr);
      grad.addColorStop(0, "rgba(255,255,255,.22)"); grad.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = grad; g.fillRect(cx - rr, cy - rr, rr * 2, rr * 2);
    }
  }
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
