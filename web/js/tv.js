"use strict";
/* Klangstation – „Läuft gerade“-Bildschirm. Liest nur den Zustand über den WebSocket. */
const $ = (s) => document.querySelector(s);
const KIND = { file: "Bibliothek", radio: "Webradio", cd: "Audio-CD", spotify: "Spotify Connect", airplay: "AirPlay",
  upnp: "UPnP/DLNA", bluetooth: "Bluetooth" };

let S = null, receivedAt = 0, lastArt = null;

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
  // „Läuft gerade“ bei Wiedergabe und kurz pausiert; sonst Bildschirmschoner
  const active = n.kind && (n.state === "play" || n.state === "pause") && (n.title || n.artist);
  $("#playing").hidden = !active;
  $("#idle").hidden = !!active;
  if (!active) return;
  $("#playing").classList.toggle("paused", n.state === "pause");
  $("#badge").textContent = (KIND[n.kind] || "") + (n.extra ? " · " + n.extra : "") + (n.state === "pause" ? " · Pause" : "");
  $("#title").textContent = n.title || "";
  $("#artist").textContent = n.artist || "";
  $("#album").textContent = n.album || "";
  $("#format").textContent = audioFormat(n);
  setArt(n.art || null);
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

function clock() {
  const d = new Date();
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  $("#clock").textContent = time;
  $("#idle-time").textContent = time;
  $("#idle-date").textContent = d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" });
}

// Bildschirmschoner: Uhr jede Minute an eine andere Stelle, damit nichts einbrennt
function moveIdle() {
  const box = $("#idle-box");
  const w = window.innerWidth, h = window.innerHeight;
  const bw = box.offsetWidth || 400, bh = box.offsetHeight || 200;
  box.style.left = Math.round(Math.random() * Math.max(0, w - bw)) + "px";
  box.style.top = Math.round(h * 0.12 + Math.random() * Math.max(0, h * 0.76 - bh)) + "px";
}

function connect() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") { S = msg.data; receivedAt = performance.now(); render(); }
  };
  ws.onclose = (ev) => {
    $("#idle-hint").textContent = ev.code === 4401
      ? "Anmeldung nötig – bitte Klangstation im Browser öffnen und anmelden"
      : "Verbindung zur Klangstation wird hergestellt …";
    $("#playing").hidden = true; $("#idle").hidden = false;
    setTimeout(connect, ev.code === 4401 ? 15000 : 2000);
  };
  ws.onopen = () => { $("#idle-hint").textContent = "Bereit"; };
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
  g.globalCompositeOperation = "lighter";
  for (let k = 0; k < 3; k++) {
    g.beginPath();
    for (let x = 0; x <= w; x += 12) {
      const y = h * (0.62 + k * 0.08) + Math.sin(x / (180 + k * 60) + s * (0.25 + k * 0.1)) * h * 0.06 * level
        + Math.sin(x / 90 + s * 0.6 + k) * h * 0.015 * level;
      x === 0 ? g.moveTo(x, y) : g.lineTo(x, y);
    }
    g.strokeStyle = ["rgba(111,211,255,.35)", "rgba(80,120,255,.28)", "rgba(180,90,255,.22)"][k];
    g.lineWidth = 2 + level * 3;
    g.stroke();
  }
  g.globalCompositeOperation = "source-over";
}

clock();
setInterval(clock, 1000);
setInterval(tick, 500);
moveIdle();
setInterval(moveIdle, 60000);
requestAnimationFrame(draw);
connect();
