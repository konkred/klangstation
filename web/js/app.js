"use strict";

/* =========================================================== Helfer */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enc = encodeURIComponent;

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

let toastTimer;
function toast(msg, err = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("err", err);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
}

async function api(path, opts = {}) {
  const init = { headers: {} };
  if (opts.body !== undefined) {
    init.method = "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res, data = null;
  try {
    res = await fetch(path, init);
  } catch (e) {
    toast("Keine Verbindung zur Klangstation", true);
    throw e;
  }
  try { data = await res.json(); } catch (e) { /* leere Antwort */ }
  if (res.status === 401 && data && data.auth && !opts.retried) {
    // Geschützter Bereich: anmelden und die Anfrage einmal wiederholen
    await requireLogin("Für diese Aktion ist eine Anmeldung nötig.");
    return api(path, Object.assign({}, opts, { retried: true }));
  }
  if (!res.ok) {
    const msg = (data && data.error) || "Fehler " + res.status;
    if (!opts.quiet) toast(msg, true);
    throw new Error(msg);
  }
  return data;
}
const post = (path, body = {}) => api(path, { body });

/* =========================================================== Anmeldung */
let authInfo = { enabled: false, scope: "settings", logged_in: true };
let loginWait = null;

async function refreshAuth() {
  try { authInfo = await (await fetch("/api/auth/status")).json(); } catch (e) { /* offline */ }
  return authInfo;
}

function requireLogin(message, mandatory = false) {
  if (loginWait) return loginWait.promise;
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  loginWait = { promise, resolve, reject };
  $("#login-msg").textContent = message || "Bitte gib das Passwort ein.";
  $("#login-err").textContent = "";
  $("#login-cancel").hidden = mandatory;
  $("#login").hidden = false;
  setTimeout(() => $("#login-pw").focus(), 50);
  return promise;
}

$("#login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: $("#login-pw").value }) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { $("#login-err").textContent = data.error || "Anmeldung fehlgeschlagen"; $("#login-pw").select(); return; }
  $("#login-pw").value = "";
  $("#login").hidden = true;
  await refreshAuth();
  const w = loginWait; loginWait = null;
  if (w) w.resolve();
});
$("#login-cancel").onclick = () => {
  $("#login").hidden = true;
  const w = loginWait; loginWait = null;
  if (w) w.reject(new Error("Anmeldung abgebrochen"));
};

const KIND_LABEL = { file: "Bibliothek", radio: "Webradio", cd: "Audio-CD", spotify: "Spotify Connect", airplay: "AirPlay",
  upnp: "UPnP/DLNA", bluetooth: "Bluetooth" };
// Quellen, die ausschließlich in der App auf dem Handy gesteuert werden
const APP_ONLY = new Set(["spotify", "airplay"]);
const LOCAL_KINDS = new Set(["file", "radio", "cd"]);
const ICON = (id) => `<svg><use href="#i-${id}"/></svg>`;

/* =========================================================== Zustand & WebSocket */
let S = null;
let receivedAt = 0;
let settings = null;
let queueItems = [];
let seeking = false;

function connect() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  let ping;
  ws.onopen = () => { ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000); loadQueue(); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") { S = msg.data; receivedAt = performance.now(); render(); }
    else if (msg.type === "queue") loadQueue();
    else if (msg.type === "library") onLibraryChanged();
    else if (msg.type === "shares") {
      if (settingsRes) settingsRes.shares = msg.data;
      if (currentView === "settings") renderShares();
    }
    else if (msg.type === "playlists") { if (currentView === "library" && lib.tab === "playlists") renderLibrary(); }
    // Einstellungen wurden woanders geändert; ein offenes Optionen-Formular bleibt unangetastet
    else if (msg.type === "settings") loadSettings(true).then(() => {
      if (currentView === "cd") renderCD();
      if (currentView === "settings") { renderShares(); renderAuthState(); }
    });
  };
  ws.onclose = async (ev) => {
    clearInterval(ping);
    $("#lamps").innerHTML = '<span class="lamp"><span>Verbindung getrennt…</span></span>';
    if (ev.code === 4401) {
      // Sitzung abgelaufen oder Schutz eingeschaltet
      await refreshAuth();
      try { await requireLogin("Bitte melde dich an.", true); } catch (e) { /* bleibt offen */ }
    }
    setTimeout(connect, 2000);
  };
}

function elapsedNow() {
  if (!S || !S.now) return 0;
  let e = S.now.elapsed || 0;
  if (S.now.state === "play") e += (performance.now() - receivedAt) / 1000;
  return S.now.duration ? Math.min(e, S.now.duration) : e;
}

function audioFormat(n) {
  const parts = [];
  if (n.format) {
    const [rate, bits, ch] = n.format.split(":");
    if (rate && rate !== "*") parts.push((rate / 1000).toLocaleString("de-DE") + " kHz");
    if (bits && bits !== "*" && bits !== "f") parts.push(bits + " bit");
    if (bits === "dsd" || (rate || "").startsWith("dsd")) parts.push("DSD");
    if (ch) parts.push(ch === "2" ? "Stereo" : ch === "1" ? "Mono" : ch + " Kanäle");
  }
  if (n.bitrate && n.bitrate !== "0") parts.push(n.bitrate + " kbit/s");
  return parts.join(" · ");
}

/* =========================================================== Rendern */
let lastArt = null;
function setArt(img, fallback, url) {
  if (url === lastArt) return;
  lastArt = url;
  if (!url) { img.hidden = true; fallback.hidden = false; return; }
  img.onload = () => { img.hidden = false; fallback.hidden = true; };
  img.onerror = () => { img.hidden = true; fallback.hidden = false; };
  img.referrerPolicy = "no-referrer";
  img.src = url;
}

function render() {
  if (!S) return;
  const n = S.now || {};
  const remote = APP_ONLY.has(n.kind);
  const playing = n.state === "play";

  $("#tb-device").textContent = S.device_name;
  $("#tb-output").textContent = "Ausgabe: " + (S.output || "–");
  const sv = S.services || {};
  const lamp = (name, label, key) => {
    const s = sv[key] || {};
    if (!s.available && key !== "mpd") return "";
    const cls = ["lamp", s.running ? "on" : "", S.source === key && playing ? "active" : ""].join(" ");
    const title = !s.available ? "nicht installiert" : s.running ? "läuft" : "aus";
    return `<span class="${cls}" title="${label}: ${title}"><span>${label}</span></span>`;
  };
  $("#lamps").innerHTML = lamp("mpd", "Player", "mpd") + lamp("airplay", "AirPlay", "airplay") +
    lamp("spotify", "Spotify", "spotify") + lamp("upnp", "UPnP", "upnp") + lamp("bluetooth", "Bluetooth", "bluetooth");

  // Wiedergabe-Ansicht
  const src = KIND_LABEL[n.kind] || "";
  $("#np-source").textContent = src + (n.extra ? " · " + n.extra : "");
  $("#np-title").textContent = n.title || (n.kind ? "" : "Keine Wiedergabe");
  $("#np-artist").textContent = n.artist || "";
  $("#np-album").textContent = n.album || "";
  $("#np-format").textContent = audioFormat(n);
  setArt($("#np-art"), $("#np-fallback"), n.art || null);

  // Transport
  $("#play-icon").setAttribute("href", playing ? "#i-pause" : "#i-play");
  $("#b-play").title = playing ? "Pause" : "Wiedergabe";
  $("#b-shuffle").classList.toggle("on", !!S.random);
  $("#b-repeat").classList.toggle("on", !!S.repeat);
  const seek = $("#seek");
  seek.disabled = remote || n.kind === "bluetooth" || !n.duration;
  const vol = $("#vol");
  // Bei AirPlay/Spotify zeigt der Regler die Lautstärke des Handys nur an
  vol.disabled = remote || S.volume < 0;
  vol.title = remote ? "Lautstärke wird am Handy eingestellt" : "Lautstärke";
  if (!vol.matches(":active") && S.volume >= 0) { vol.value = S.volume; paintRange(vol); }
  $("#vol-icon").setAttribute("href", S.volume === 0 ? "#i-mute" : "#i-vol");

  const line = n.title ? (playing ? "Wird wiedergegeben: " : n.state === "pause" ? "Angehalten: " : "Bereit: ") +
    n.title + (n.artist ? " – " + n.artist : "") : S.mpd_online ? "Bereit" : "Player startet…";
  $("#mini-text").textContent = line;
  statusRight();
  const tm = S.timers || {};
  $("#b-timer").classList.toggle("on", !!tm.sleep);
  if (!$("#timer-modal").hidden) renderTimers();
  document.title = n.title && playing ? n.title + " – Klangstation" : "Klangstation";

  // Warteschlange: aktuellen Titel markieren
  $$("#queue li").forEach((li) => li.classList.toggle("cur", LOCAL_KINDS.has(n.kind) && +li.dataset.pos === S.queue_pos));

  if (currentView === "cd") renderCD();
  if (currentView === "settings") renderBluetooth();
  vis.playing = playing;
  tick();
}

function paintRange(r) {
  const p = r.max > 0 ? ((r.value - r.min) / (r.max - r.min)) * 100 : 0;
  r.style.setProperty("--p", p + "%");
}

function tick() {
  if (!S || !S.now) return;
  const n = S.now;
  const e = elapsedNow();
  $("#t-elapsed").textContent = fmt(e);
  $("#t-total").textContent = n.duration ? fmt(n.duration) : n.kind === "radio" ? "Live" : "0:00";
  const seek = $("#seek");
  if (!seeking) {
    seek.max = Math.max(1, Math.round((n.duration || 0) * 10));
    seek.value = Math.round(e * 10);
    paintRange(seek);
  }
}
setInterval(tick, 500);

/* =========================================================== Warteschlange */
async function loadQueue() {
  const ol = $("#queue");
  try {
    queueItems = await api("/api/queue", { quiet: true });
  } catch (e) {
    ol.innerHTML = '<div class="queue-empty">Der Player ist noch nicht bereit…</div>';
    return;
  }
  if (!queueItems.length) {
    ol.innerHTML = '<div class="queue-empty">Die Wiedergabeliste ist leer.<br>Wähle Musik in der Medienbibliothek, im Radio oder von CD.</div>';
    return;
  }
  ol.innerHTML = queueItems.map((q) => `
    <li data-id="${q.id}" data-pos="${q.pos}">
      <span class="q-t">${esc(q.title)}<small>${esc(q.artist || KIND_LABEL[q.kind] || "")}</small></span>
      <span class="q-d">${q.duration ? fmt(q.duration) : ""}</span>
      <button class="q-x" title="Entfernen" data-remove="${q.id}">${ICON("x")}</button>
    </li>`).join("");
  if (S) render();
}

$("#queue").addEventListener("click", (ev) => {
  const rm = ev.target.closest("[data-remove]");
  if (rm) { post("/api/queue/remove", { id: +rm.dataset.remove }); return; }
  const li = ev.target.closest("li[data-id]");
  if (li) post("/api/queue/play", { id: +li.dataset.id });
});
$("#q-clear").onclick = () => post("/api/queue/clear");

/* =========================================================== Transport */
$("#b-play").onclick = () => {
  const n = (S && S.now) || {};
  if (APP_ONLY.has(n.kind)) {
    toast("AirPlay und Spotify werden in der App auf dem Handy gesteuert. Stopp beendet die Verbindung.");
    return;
  }
  post("/api/player/toggle");
};
$("#b-stop").onclick = () => post("/api/player/stop");
$("#b-prev").onclick = () => post("/api/player/prev");
$("#b-next").onclick = () => post("/api/player/next");
$("#b-shuffle").onclick = () => post("/api/player/mode", { random: !(S && S.random) });
$("#b-repeat").onclick = () => post("/api/player/mode", { repeat: !(S && S.repeat) });

const seekEl = $("#seek");
seekEl.addEventListener("input", () => { seeking = true; paintRange(seekEl); $("#t-elapsed").textContent = fmt(seekEl.value / 10); });
seekEl.addEventListener("change", async () => {
  try { await post("/api/player/seek", { position: seekEl.value / 10 }); } finally { seeking = false; }
});

const volEl = $("#vol");
const sendVol = debounce((v) => post("/api/player/volume", { volume: v }), 120);
volEl.addEventListener("input", () => { paintRange(volEl); sendVol(+volEl.value); });
let volBeforeMute = 50;
$("#b-mute").onclick = () => {
  if (!S || S.volume < 0) return;
  if (S.volume > 0) { volBeforeMute = S.volume; post("/api/player/volume", { volume: 0 }); }
  else post("/api/player/volume", { volume: volBeforeMute || 50 });
};

/* =========================================================== Navigation */
let currentView = "now";
function showView(name) {
  if (!$("#view-" + name)) name = "now";
  currentView = name;
  $$(".view").forEach((v) => { v.hidden = v.id !== "view-" + name; });
  $$("#taskbar a").forEach((a) => a.classList.toggle("on", a.dataset.view === name));
  vis.visible = name === "now";
  if (name === "library") renderLibrary();
  if (name === "radio") renderRadio();
  if (name === "cd") renderCD();
  if (name === "settings") {
    if (authInfo.enabled && !authInfo.logged_in) {
      requireLogin("Die Optionen sind mit einem Passwort geschützt.")
        .then(loadSettings)
        .catch(() => { location.hash = "#now"; });
    } else {
      loadSettings();
    }
  }
}
window.addEventListener("hashchange", () => showView(location.hash.slice(1)));

function segTabs(container, onChange) {
  container.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-tab]");
    if (!b) return;
    $$("button", container).forEach((x) => x.classList.toggle("on", x === b));
    onChange(b.dataset.tab);
  });
}

/* =========================================================== Gemeinsame Tabellen */
function songTable(songs, { showAlbum = true } = {}) {
  if (!songs.length) return '<div class="empty">Keine Titel gefunden.</div>';
  return `<table class="grid"><thead><tr>
      <th class="num">Nr.</th><th>Titel</th><th class="hide-m">Interpret</th>${showAlbum ? '<th class="hide-m">Album</th>' : ""}
      <th class="dur">Länge</th><th class="act"></th></tr></thead><tbody>
    ${songs.map((s, i) => `<tr data-uri="${esc(s.uri)}">
      <td class="num">${esc(String(s.track || "").split("/")[0] || i + 1)}</td>
      <td title="${esc(s.name)}">${esc(s.name)}</td>
      <td class="hide-m">${esc(s.artist)}</td>${showAlbum ? `<td class="hide-m">${esc(s.album)}</td>` : ""}
      <td class="dur">${s.duration ? fmt(s.duration) : ""}</td>
      <td class="act act3">${rowButtons()}</td>
    </tr>`).join("")}</tbody></table>`;
}

const rowButtons = () =>
  `<button class="rowbtn" data-act="play" title="Abspielen">${ICON("play")}</button>` +
  `<button class="rowbtn" data-act="add" title="An die aktuelle Wiedergabeliste anhängen">${ICON("plus")}</button>` +
  `<button class="rowbtn" data-act="pl" title="Zu einer gespeicherten Wiedergabeliste …">${ICON("list")}</button>`;

function bindSongTable(root, allUris) {
  root.onclick = (ev) => {
    const btn = ev.target.closest("[data-act]");
    const tr = ev.target.closest("tr[data-uri]");
    if (!btn || !tr) return;
    if (btn.dataset.act === "add") { post("/api/queue/add", { uris: [tr.dataset.uri] }).then(() => toast("An die aktuelle Wiedergabeliste angehängt")); return; }
    if (btn.dataset.act === "pl") { pickPlaylist([tr.dataset.uri]); return; }
    playFrom(allUris, tr.dataset.uri);
  };
  root.ondblclick = (ev) => {
    const tr = ev.target.closest("tr[data-uri]");
    if (tr) playFrom(allUris, tr.dataset.uri);
  };
}

async function playFrom(uris, start) {
  // ab dem gewählten Titel abspielen, die restlichen Titel folgen
  const i = Math.max(0, uris.indexOf(start));
  await post("/api/queue/add", { uris: uris.slice(i).concat(uris.slice(0, i)), mode: "play" });
}

/* =========================================================== Bibliothek */
const lib = { tab: "albums", path: "", album: null, playlist: null, q: "", albums: null };

segTabs($("#lib-tabs"), (tab) => { lib.tab = tab; lib.album = null; lib.playlist = null; lib.q = ""; $("#lib-search").value = ""; renderLibrary(); });
$("#lib-search").addEventListener("input", debounce((ev) => { lib.q = ev.target.value.trim(); renderLibrary(); }, 350));
$("#lib-update").onclick = () => post("/api/library/update").then(() => toast("Bibliothek wird neu eingelesen…"));

function onLibraryChanged() {
  lib.albums = null;
  if (currentView === "library") renderLibrary();
}

async function renderLibrary() {
  const body = $("#lib-body"), crumbs = $("#lib-crumbs");
  try {
    if (lib.q.length >= 2) {
      crumbs.innerHTML = `Suchergebnisse für „${esc(lib.q)}“`;
      const songs = await api("/api/library/search?q=" + enc(lib.q));
      body.innerHTML = songTable(songs);
      bindSongTable(body, songs.map((s) => s.uri));
    } else if (lib.tab === "albums") {
      await renderAlbums(body, crumbs);
    } else if (lib.tab === "playlists") {
      await renderPlaylists(body, crumbs);
    } else {
      await renderFolder(body, crumbs);
    }
  } catch (e) {
    body.innerHTML = '<div class="empty">Die Bibliothek ist gerade nicht erreichbar.</div>';
  }
}

const artUrl = (album, artist) => "/api/art?album=" + enc(album) + "&artist=" + enc(artist);

async function renderAlbums(body, crumbs) {
  if (lib.album) {
    const { album, artist } = lib.album;
    crumbs.innerHTML = `<a data-back>Alle Alben</a> › ${esc(album)}`;
    const songs = await api("/api/library/album?album=" + enc(album) + "&artist=" + enc(artist));
    const uris = songs.map((s) => s.uri);
    const total = songs.reduce((a, s) => a + (s.duration || 0), 0);
    body.onclick = body.ondblclick = null;
    body.innerHTML = `<div class="album-head"><div class="art">${ICON("note")}<img src="${artUrl(album, artist)}" alt="" onerror="this.remove()"></div>
      <div><h2>${esc(album)}</h2><div class="sub">${esc(artist || "Verschiedene Interpreten")} · ${songs.length} Titel · ${fmt(total)}</div>
      <button class="btn primary" id="alb-play">${ICON("play")}Album abspielen</button> <button class="btn" id="alb-add">${ICON("plus")}Anhängen</button>
      <button class="btn" id="alb-pl">${ICON("list")}Zu Wiedergabeliste …</button></div></div>
      <div id="alb-tracks">${songTable(songs, { showAlbum: false })}</div>`;
    bindSongTable($("#alb-tracks"), uris);
    $("#alb-play").onclick = () => post("/api/queue/add", { uris, mode: "play" });
    $("#alb-add").onclick = () => post("/api/queue/add", { uris }).then(() => toast("Album angehängt"));
    $("#alb-pl").onclick = () => pickPlaylist(uris);
    crumbs.querySelector("[data-back]").onclick = () => { lib.album = null; renderLibrary(); };
    return;
  }
  crumbs.innerHTML = "";
  if (!lib.albums) lib.albums = await api("/api/library/albums");
  if (!lib.albums.length) {
    body.innerHTML = '<div class="empty">Noch keine Alben gefunden.<br>Stecke einen USB-Stick oder eine SD-Karte mit Musik an. Sie wird automatisch eingelesen.</div>';
    return;
  }
  body.innerHTML = `<div class="albums">${lib.albums.map((a, i) => `
    <div class="album" data-i="${i}">
      <div class="art">${ICON("note")}<img loading="lazy" src="${artUrl(a.album, a.artist)}" alt="" onerror="this.remove()"></div>
      <b title="${esc(a.album)}">${esc(a.album)}</b><span>${esc(a.artist || "Verschiedene")}</span>
    </div>`).join("")}</div>`;
  body.onclick = (ev) => {
    const el = ev.target.closest(".album[data-i]");
    if (el) { lib.album = lib.albums[+el.dataset.i]; renderLibrary(); }
  };
  body.ondblclick = null;
}

async function renderFolder(body, crumbs) {
  const parts = lib.path ? lib.path.split("/") : [];
  const media = (S && S.media) || [];
  const label = (seg, i) => (i === 0 ? (media.find((m) => m.dir === seg) || {}).label || seg : seg);
  crumbs.innerHTML = `<a data-path="">Alle Laufwerke</a>` + parts.map((p, i) =>
    ` › <a data-path="${esc(parts.slice(0, i + 1).join("/"))}">${esc(label(p, i))}</a>`).join("");
  $$("a[data-path]", crumbs).forEach((a) => { a.onclick = () => { lib.path = a.dataset.path; renderLibrary(); }; });

  const items = await api("/api/library/browse?path=" + enc(lib.path));
  const dirs = items.filter((x) => x.type === "dir");
  const songs = items.filter((x) => x.type === "song");
  if (!items.length) {
    body.innerHTML = lib.path ? '<div class="empty">Dieser Ordner ist leer.</div>'
      : '<div class="empty">Kein Datenträger gefunden.<br>USB-Sticks und SD-Karten werden beim Einstecken automatisch eingebunden.</div>';
    return;
  }
  const dirIcon = (d) => {
    if (lib.path) return ICON("folder");
    const m = media.find((x) => x.dir === d.uri);
    return ICON(m ? "usb" : d.uri.startsWith("Netz-") ? "net" : "folder");
  };
  let html = "";
  if (dirs.length) {
    html += `<table class="grid"><thead><tr><th class="ico"></th><th>Name</th><th class="act"></th></tr></thead><tbody>
      ${dirs.map((d) => `<tr data-dir="${esc(d.uri)}"><td class="ico">${dirIcon(d)}</td><td>${esc(d.name)}</td>
        <td class="act act3"><button class="rowbtn" data-dplay title="Ordner abspielen">${ICON("play")}</button><button class="rowbtn" data-dadd title="Ordner anhängen">${ICON("plus")}</button><button class="rowbtn" data-dpl title="Ordner zu einer gespeicherten Wiedergabeliste …">${ICON("list")}</button></td></tr>`).join("")}
      </tbody></table>`;
  }
  if (songs.length) html += `<div id="folder-songs">${songTable(songs)}</div>`;
  body.innerHTML = html;
  body.onclick = (ev) => {
    const tr = ev.target.closest("tr[data-dir]");
    if (!tr) return;
    if (ev.target.closest("[data-dplay]")) post("/api/queue/add", { uris: [tr.dataset.dir], mode: "play" });
    else if (ev.target.closest("[data-dadd]")) post("/api/queue/add", { uris: [tr.dataset.dir] }).then(() => toast("Ordner angehängt"));
    else if (ev.target.closest("[data-dpl]")) pickPlaylist([tr.dataset.dir]);
    else { lib.path = tr.dataset.dir; renderLibrary(); }
  };
  body.ondblclick = null;
  if (songs.length) bindSongTable($("#folder-songs"), songs.map((s) => s.uri));
}

/* =========================================================== Wiedergabelisten (gespeichert) */
async function renderPlaylists(body, crumbs) {
  body.ondblclick = null;
  if (lib.playlist) {
    const name = lib.playlist;
    crumbs.innerHTML = `<a data-back>Alle Wiedergabelisten</a> › ${esc(name)}`;
    crumbs.querySelector("[data-back]").onclick = () => { lib.playlist = null; renderLibrary(); };
    const tracks = await api("/api/playlist?name=" + enc(name));
    const total = tracks.reduce((a, t) => a + (t.duration || 0), 0);
    body.innerHTML = `<div class="pl-head">${ICON("list")}<div><h2>${esc(name)}</h2>
        <div class="sub">${tracks.length} Einträge${total ? " · " + fmt(total) : ""}</div></div>
        <div class="acts">
          <button class="btn primary" data-pl-act="play">${ICON("play")}Abspielen</button>
          <button class="btn" data-pl-act="append">${ICON("plus")}Anhängen</button>
          <button class="btn" data-pl-act="rename">Umbenennen</button>
          <button class="btn" data-pl-act="delete">Löschen</button>
        </div></div>
      ${tracks.length ? `<table class="grid"><thead><tr><th class="num">Nr.</th><th>Titel</th><th class="hide-m">Interpret</th>
        <th class="dur">Länge</th><th class="act"></th></tr></thead><tbody>
        ${tracks.map((t) => `<tr data-pos="${t.pos}"><td class="num">${t.pos + 1}</td><td title="${esc(t.name)}">${esc(t.name)}</td>
          <td class="hide-m">${esc(t.artist)}</td><td class="dur">${t.duration ? fmt(t.duration) : ""}</td>
          <td class="act"><button class="rowbtn" data-t="play" title="Ab hier abspielen">${ICON("play")}</button><button class="rowbtn" data-t="remove" title="Aus der Liste entfernen">${ICON("x")}</button></td></tr>`).join("")}
        </tbody></table>` : '<div class="empty">Diese Wiedergabeliste ist leer.</div>'}`;
    body.onclick = async (ev) => {
      const act = ev.target.closest("[data-pl-act]");
      if (act) {
        const a = act.dataset.plAct;
        if (a === "play") await post("/api/playlist/play", { name });
        else if (a === "append") { await post("/api/playlist/append", { name }); toast("An die aktuelle Wiedergabeliste angehängt"); }
        else if (a === "rename") {
          const nn = prompt("Neuer Name der Wiedergabeliste:", name);
          if (nn && nn.trim() && nn.trim() !== name) { await post("/api/playlist/rename", { name, new_name: nn.trim() }); lib.playlist = nn.trim(); renderLibrary(); }
        } else if (a === "delete" && confirm(`Wiedergabeliste „${name}“ löschen?`)) {
          await post("/api/playlist/delete", { name }); lib.playlist = null; renderLibrary();
        }
        return;
      }
      const btn = ev.target.closest("[data-t]"), tr = ev.target.closest("tr[data-pos]");
      if (!btn || !tr) return;
      if (btn.dataset.t === "play") await post("/api/playlist/play", { name, start: +tr.dataset.pos });
      else { await post("/api/playlist/remove_track", { name, pos: +tr.dataset.pos }); renderLibrary(); }
    };
    body.ondblclick = (ev) => {
      const tr = ev.target.closest("tr[data-pos]");
      if (tr) post("/api/playlist/play", { name, start: +tr.dataset.pos });
    };
    return;
  }
  crumbs.innerHTML = "";
  const lists = await api("/api/playlists");
  if (!lists.length) {
    body.innerHTML = '<div class="empty">Noch keine Wiedergabelisten.<br>Speichere die aktuelle Wiedergabeliste über „Speichern“ oder füge Titel mit dem Listen-Symbol hinzu.</div>';
    body.onclick = null;
    return;
  }
  body.innerHTML = `<table class="grid"><thead><tr><th class="ico"></th><th>Wiedergabeliste</th><th class="hide-m" style="width:160px">Geändert</th><th class="act"></th></tr></thead><tbody>
    ${lists.map((p) => `<tr data-name="${esc(p.name)}"><td class="ico">${ICON("list")}</td><td>${esc(p.name)}</td>
      <td class="hide-m">${p.modified ? esc(new Date(p.modified).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" })) : ""}</td>
      <td class="act"><button class="rowbtn" data-p="play" title="Abspielen">${ICON("play")}</button><button class="rowbtn" data-p="delete" title="Löschen">${ICON("x")}</button></td></tr>`).join("")}
    </tbody></table>`;
  body.onclick = async (ev) => {
    const tr = ev.target.closest("tr[data-name]");
    if (!tr) return;
    const name = tr.dataset.name, btn = ev.target.closest("[data-p]");
    if (btn && btn.dataset.p === "play") await post("/api/playlist/play", { name });
    else if (btn && btn.dataset.p === "delete") {
      if (confirm(`Wiedergabeliste „${name}“ löschen?`)) { await post("/api/playlist/delete", { name }); renderLibrary(); }
    } else { lib.playlist = name; renderLibrary(); }
  };
}

/* Auswahl, zu welcher gespeicherten Liste etwas hinzugefügt wird */
let pickUris = [], pickStations = [];
async function pickPlaylist(uris, stations = []) {
  pickUris = uris;
  pickStations = stations;  // Sendername/Logo für Radio-Einträge
  let lists = [];
  try { lists = await api("/api/playlists"); } catch (e) { return; }
  $("#pl-pick-list").innerHTML = lists.length
    ? lists.map((p) => `<button type="button" data-name="${esc(p.name)}">${ICON("list")}${esc(p.name)}</button>`).join("")
    : '<p class="hint">Noch keine Wiedergabelisten vorhanden.</p>';
  $("#pl-pick-new").value = "";
  $("#pl-pick").hidden = false;
}
async function addToPlaylist(name) {
  await post("/api/playlist/add", { name, uris: pickUris, stations: pickStations });
  $("#pl-pick").hidden = true;
  toast(`Zu „${name}“ hinzugefügt`);
}
$("#pl-pick-list").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-name]");
  if (b) addToPlaylist(b.dataset.name);
});
$("#pl-pick-create").onclick = () => {
  const name = $("#pl-pick-new").value.trim();
  if (!name) { $("#pl-pick-new").focus(); return; }
  addToPlaylist(name);
};
$("#pl-pick-new").addEventListener("keydown", (ev) => { if (ev.key === "Enter") $("#pl-pick-create").click(); });
$("#pl-pick-cancel").onclick = () => { $("#pl-pick").hidden = true; };

$("#q-save").onclick = async () => {
  if (!queueItems.length) { toast("Die aktuelle Wiedergabeliste ist leer."); return; }
  const name = (prompt("Aktuelle Wiedergabeliste speichern unter:") || "").trim();
  if (!name) return;
  try {
    await api("/api/playlist/save", { body: { name }, quiet: true });
  } catch (e) {
    if (!/gibt es schon/.test(e.message)) { toast(e.message, true); return; }
    if (!confirm(e.message + ". Überschreiben?")) return;
    await post("/api/playlist/save", { name, overwrite: true });
  }
  toast(`Als „${name}“ gespeichert`);
};

/* =========================================================== Radio */
const radio = { tab: "favorites", q: "", tag: "", country: null, list: [] };

segTabs($("#radio-tabs"), (tab) => { radio.tab = tab; radio.tag = ""; radio.q = ""; $("#radio-search").value = ""; renderRadio(); });
$("#radio-search").addEventListener("input", debounce((ev) => { radio.q = ev.target.value.trim(); renderRadio(); }, 400));
$("#radio-country").addEventListener("change", (ev) => { radio.country = ev.target.value; renderRadio(); });

let countriesLoaded = false;
async function loadCountries() {
  if (countriesLoaded) return;
  try {
    const list = await api("/api/radio/countries", { quiet: true });
    const opts = list.map((c) => `<option value="${esc(c.code)}">${esc(c.name)} (${c.count})</option>`).join("");
    $("#radio-country").insertAdjacentHTML("beforeend", opts);
    $("#set-country").insertAdjacentHTML("beforeend", opts);
    countriesLoaded = true;
    if (radio.country === null && settings) radio.country = settings.radio_country || "";
    $("#radio-country").value = radio.country || "";
    if (settings) $("#set-country").value = settings.radio_country || "";
  } catch (e) { /* offline */ }
}

const favs = () => (settings && settings.radio_favorites) || [];
const isFav = (st) => favs().some((f) => f.uuid === st.uuid);

async function renderRadio() {
  const body = $("#radio-body"), crumbs = $("#radio-crumbs");
  if (!settings) await loadSettings(true);
  loadCountries();
  if (radio.country === null) radio.country = settings.radio_country || "";
  const country = radio.country || "";
  try {
    if (radio.q.length >= 2) {
      crumbs.textContent = `Suche nach „${radio.q}“`;
      radio.list = await api(`/api/radio/search?q=${enc(radio.q)}&country=${enc(country)}&limit=100`);
    } else if (radio.tab === "favorites") {
      crumbs.textContent = "";
      radio.list = favs();
      if (!radio.list.length) {
        body.innerHTML = '<div class="empty">Noch keine Favoriten. Markiere Sender mit dem Stern.</div>';
        return;
      }
    } else if (radio.tab === "top") {
      crumbs.textContent = "Meistgehörte Sender" + (country ? " · " + ($("#radio-country").selectedOptions[0] || {}).textContent : "");
      radio.list = await api(`/api/radio/search?country=${enc(country)}&limit=100`);
    } else if (radio.tab === "genres" && !radio.tag) {
      crumbs.textContent = "Genre wählen";
      const tags = await api("/api/radio/tags");
      body.innerHTML = `<div class="tags">${tags.map((t) => `<button class="tag" data-tag="${esc(t.name)}">${esc(t.name)} <small>${t.count}</small></button>`).join("")}</div>`;
      body.onclick = (ev) => { const b = ev.target.closest("[data-tag]"); if (b) { radio.tag = b.dataset.tag; renderRadio(); } };
      return;
    } else {
      crumbs.innerHTML = `<a data-back>Genres</a> › ${esc(radio.tag)}`;
      crumbs.querySelector("[data-back]").onclick = () => { radio.tag = ""; renderRadio(); };
      radio.list = await api(`/api/radio/search?tag=${enc(radio.tag)}&country=${enc(country)}&limit=100`);
    }
  } catch (e) {
    body.innerHTML = '<div class="empty">Radio-Verzeichnis nicht erreichbar. Besteht eine Internetverbindung?</div>';
    return;
  }
  body.innerHTML = radio.list.length ? `<table class="grid"><thead><tr><th class="ico"></th><th>Sender</th>
      <th class="hide-m">Land</th><th class="hide-m" style="width:120px">Format</th><th class="act"></th></tr></thead><tbody>
    ${radio.list.map((st, i) => `<tr data-i="${i}">
      <td class="ico">${st.favicon ? `<img loading="lazy" referrerpolicy="no-referrer" src="${esc(st.favicon)}" alt="" onerror="this.outerHTML='<svg><use href=&quot;#i-radio&quot;/></svg>'">` : ICON("radio")}</td>
      <td title="${esc(st.name)}">${esc(st.name)}</td>
      <td class="hide-m">${esc(st.country || st.countrycode || "")}</td>
      <td class="hide-m">${esc([st.codec, st.bitrate ? st.bitrate + " kbit/s" : ""].filter(Boolean).join(" · "))}</td>
      <td class="act act3"><button class="rowbtn ${isFav(st) ? "fav" : ""}" data-fav title="Favorit">${ICON("star")}</button><button class="rowbtn" data-pl title="Zu einer gespeicherten Wiedergabeliste …">${ICON("list")}</button><button class="rowbtn" data-play title="Abspielen">${ICON("play")}</button></td>
    </tr>`).join("")}</tbody></table>` : '<div class="empty">Keine Sender gefunden.</div>';
  body.onclick = async (ev) => {
    const tr = ev.target.closest("tr[data-i]");
    if (!tr) return;
    const st = radio.list[+tr.dataset.i];
    if (ev.target.closest("[data-fav]")) {
      settings.radio_favorites = await post("/api/radio/favorites", Object.assign({}, st, { favorite: !isFav(st) }));
      if (radio.tab === "favorites" && !radio.q) renderRadio();
      else ev.target.closest("[data-fav]").classList.toggle("fav", isFav(st));
    } else if (ev.target.closest("[data-pl]")) {
      pickPlaylist([st.url], [st]);
    } else if (ev.target.closest("[data-play]")) {
      playStation(st);
    }
  };
  body.ondblclick = (ev) => { const tr = ev.target.closest("tr[data-i]"); if (tr) playStation(radio.list[+tr.dataset.i]); };
}

function playStation(st) {
  post("/api/radio/play", st).then(() => toast("Sender: " + st.name));
}

/* =========================================================== CD */
const CD_STATUS = {
  none: "Kein CD-Laufwerk gefunden.",
  empty: "Keine CD eingelegt.",
  open: "Die Laufwerksschublade ist offen.",
  busy: "Laufwerk liest die CD…",
  unknown: "Laufwerksstatus unbekannt.",
};

let ripInfo = null;    // Ziele/Platzbedarf fuers Rippen (GET /api/cd/rip)
let lastRipKey = null;

function renderCD() {
  if (!S) return;
  const cd = S.cd || {};
  const has = cd.present && cd.audio;
  $("#cd-title").textContent = has ? cd.album || "Audio-CD" : "Audio-CD";
  $("#cd-artist").textContent = has ? cd.artist || "" : "";
  let status = CD_STATUS[cd.status] || "";
  if (cd.present && !cd.audio) status = "Die eingelegte Disc enthält keine Audiotitel.";
  if (has) {
    const total = (cd.tracks || []).reduce((a, t) => a + t.duration, 0);
    status = `${cd.tracks.length} Titel · ${fmt(total)}` +
      (cd.lookup === "pending" ? " · Titel werden bei MusicBrainz gesucht…" : cd.lookup === "unknown" ? " · CD ist bei MusicBrainz nicht bekannt" :
        cd.lookup === "offline" ? " · MusicBrainz gerade nicht erreichbar, wird regelmäßig erneut versucht" : "") +
      (cd.date ? " · " + cd.date : "");
  }
  $("#cd-status").textContent = status;
  if (has && cd.lookup === "unknown" && cd.submit_url) {
    $("#cd-status").insertAdjacentHTML("beforeend",
      ` · <a href="${esc(cd.submit_url)}" target="_blank" rel="noopener">Bei MusicBrainz eintragen</a>`);
  }
  const ripping = !!(S.rip && S.rip.state === "running");
  $("#cd-play").disabled = !has || ripping;
  $("#cd-eject").disabled = !cd.available || ripping;
  const ripKey = [cd.disc_id || "", cd.lookup || "", (S.media || []).map((m) => m.dir).join(","), S.rip ? S.rip.state : ""].join("|");
  if (ripKey !== lastRipKey) { lastRipKey = ripKey; loadRipInfo(); } else renderRip();
  const img = $("#cd-art");
  if (has && cd.art) {
    if (img.getAttribute("src") !== cd.art) img.src = cd.art;
    img.hidden = false; $("#cd-art-fallback").style.display = "none";
  } else {
    img.hidden = true; $("#cd-art-fallback").style.display = "";
  }
  if (settings) $("#cd-autoplay").checked = !!settings.cd_autoplay;
  const body = $("#cd-body");
  const key = has ? cd.disc_id + cd.lookup + (cd.album || "") : "none";
  if (body.dataset.key === key) return;
  body.dataset.key = key;
  body.innerHTML = has ? `<table class="grid"><thead><tr><th class="num">Nr.</th><th>Titel</th><th class="hide-m">Interpret</th><th class="dur">Länge</th><th class="act"></th></tr></thead><tbody>
    ${cd.tracks.map((t) => `<tr data-track="${t.number}"><td class="num">${t.number}</td><td>${esc(t.title || "Titel " + t.number)}</td>
      <td class="hide-m">${esc(t.artist || cd.artist || "")}</td><td class="dur">${fmt(t.duration)}</td>
      <td class="act"><button class="rowbtn" title="Ab hier abspielen">${ICON("play")}</button></td></tr>`).join("")}
    </tbody></table>` : `<div class="empty">${esc(status)}</div>`;
}

$("#cd-body").addEventListener("click", (ev) => {
  const tr = ev.target.closest("tr[data-track]");
  if (tr && ev.target.closest(".rowbtn")) post("/api/cd/play", { track: +tr.dataset.track });
});
$("#cd-body").addEventListener("dblclick", (ev) => {
  const tr = ev.target.closest("tr[data-track]");
  if (tr) post("/api/cd/play", { track: +tr.dataset.track });
});
$("#cd-play").onclick = () => post("/api/cd/play", { track: 1 });
$("#cd-eject").onclick = () => post("/api/cd/eject");
/* CD rippen */
async function loadRipInfo() {
  try { ripInfo = await api("/api/cd/rip"); } catch (e) { ripInfo = null; }
  renderRip();
}
const gb = (b) => (b / 2 ** 30).toLocaleString("de-DE", { maximumFractionDigits: 1 }) + " GB";
function fmtEta(sec) {
  if (sec == null) return "";
  if (sec < 60) return " · noch unter einer Minute";
  return ` · noch etwa ${Math.round(sec / 60)} Min.`;
}
function renderRip() {
  const cd = (S && S.cd) || {};
  const job = S && S.rip;
  const has = cd.present && cd.audio;
  const running = !!(job && job.state === "running");
  $("#cd-rip").hidden = !has && !job;
  $("#rip-form").hidden = running || !has;
  $("#rip-run").hidden = !running;
  const note = $("#rip-note");
  note.className = "rip-note";
  if (running) {
    const pct = Math.floor((job.progress || 0) * 100);
    $("#rip-bar").style.width = pct + "%";
    note.textContent = job.track ? `Titel ${job.track} von ${job.tracks}: ${job.title} · ${pct} %${fmtEta(job.eta)}` : "Wird vorbereitet …";
  } else if (job && job.state === "done") {
    note.classList.add(job.warning ? "err" : "ok");
    note.textContent = (job.warning ? job.warning + " " : "") +
      `Fertig: „${job.album}“ liegt auf „${job.target}“ unter ${job.folder}.`;
  } else if (job && job.state === "error") {
    note.classList.add("err");
    note.textContent = "Rippen fehlgeschlagen: " + job.error;
  } else if (job && job.state === "cancelled") {
    note.textContent = "Abgebrochen – angefangene Dateien wurden gelöscht.";
  } else note.textContent = "";
  if (!has || running || !ripInfo) return;
  if (!job || job.disc_id !== cd.disc_id) {
    note.className = "rip-note";
    note.textContent = cd.lookup === "pending" ? "Warte auf Titel und Cover von MusicBrainz …"
      : `Etwa ${gb(ripInfo.need)} · verlustfrei mit Fehlerkorrektur` +
        (cd.lookup === "found" ? ", mit Titeln und Cover von MusicBrainz"
          : cd.lookup === "offline" ? " – Achtung: MusicBrainz ist gerade nicht erreichbar, jetzt gerippt " +
            "bekämen die Dateien nur „Titel 1, 2 …“. Besser ein paar Minuten warten."
          : cd.lookup === "off" ? ", ohne Titelangaben (Online-Metadaten sind abgeschaltet)"
          : ", ohne Titelangaben (CD ist bei MusicBrainz unbekannt)");
  }
  const sel = $("#rip-target");
  const optKey = ripInfo.targets.map((t) => t.id + t.free).join("|");
  if (sel.dataset.key !== optKey) {
    const keep = sel.value || ripInfo.target;
    sel.dataset.key = optKey;
    sel.innerHTML = ripInfo.targets.map((t) =>
      `<option value="${esc(t.id)}"${t.free < ripInfo.need ? " disabled" : ""}>${esc(t.label)} (frei: ${gb(t.free)})</option>`).join("");
    if (ripInfo.targets.some((t) => t.id === keep)) sel.value = keep;
  }
  if (!sel.dataset.touched) $("#rip-eject").checked = !!ripInfo.eject;
  $("#rip-start").disabled = cd.lookup === "pending" || !ripInfo.targets.length;
}
$("#rip-target").onchange = () => { $("#rip-target").dataset.touched = "1"; };
$("#rip-eject").onchange = () => { $("#rip-target").dataset.touched = "1"; };
$("#rip-start").onclick = async () => {
  try {
    ripInfo = await post("/api/cd/rip", { target: $("#rip-target").value, eject: $("#rip-eject").checked });
    toast("CD wird gerippt …");
  } catch (e) { /* Meldung kam schon */ }
};
$("#rip-cancel").onclick = async () => {
  if (!confirm("Rippen abbrechen? Bereits gelesene Titel werden verworfen.")) return;
  ripInfo = await post("/api/cd/rip/cancel");
};

$("#cd-autoplay").onchange = async (ev) => {
  const res = await post("/api/settings", { cd_autoplay: ev.target.checked });
  settings = res.settings;
  toast(ev.target.checked ? "CDs werden beim Einlegen automatisch abgespielt" : "Automatisches Abspielen aus");
};

/* =========================================================== Optionen */
const KIND_TXT = { usb: "USB", hdmi: "HDMI", analog: "Analog", i2s: "DAC", other: "ALSA" };

segTabs($("#set-tabs"), (tab) => {
  $$("#settings-form fieldset").forEach((f) => { f.hidden = f.dataset.pane !== tab; });
});

async function loadSettings(silent = false) {
  let res;
  try { res = await api("/api/settings", { quiet: silent }); } catch (e) { return; }
  settings = res.settings;
  settingsRes = res;
  if (silent) return;
  fillSettings(res);
}
let settingsRes = null;

function fillSettings(res) {
  const f = $("#settings-form");
  const s = res.settings;
  for (const el of f.elements) {
    if (!el.name || el.name === "output") continue;
    if (el.type === "checkbox") el.checked = !!s[el.name];
    else if (el.name in s) el.value = s[el.name] == null ? "" : s[el.name];
  }
  const active = res.active_output || {};
  const outs = [{ id: "", label: "Automatisch wählen", detail: "USB-DAC › I²S-DAC › Analog › HDMI", kind: "other" }].concat(res.outputs);
  $("#out-list").innerHTML = outs.map((o) => `
    <label class="out"><input type="radio" name="output" value="${esc(o.id)}" ${(s.output || "") === o.id ? "checked" : ""}>
      <span class="kind ${o.kind}">${o.id ? KIND_TXT[o.kind] || "ALSA" : "AUTO"}</span>
      <span>${esc(o.label)} ${o.id && o.id === active.id ? '<span class="cur">· aktiv</span>' : ""}<small>${esc(o.detail)}${o.id ? " · " + esc(o.id) : ""}</small></span>
    </label>`).join("");
  const SVC = { mpd: "Player (MPD)", airplay: "AirPlay (shairport-sync)", spotify: "Spotify Connect (librespot)",
    upnp: "UPnP/DLNA (gmediarender)", bluetooth: "Bluetooth (bluez-alsa)" };
  $("#svc-list").innerHTML = res.services.map((d) => {
    const [cls, txt] = !d.available ? ["no", "nicht installiert"] : d.running ? ["ok", "läuft"] : ["off", "aus"];
    return `<div class="svc"><span>${SVC[d.name] || d.name}</span><span class="st ${cls}">${txt}</span></div>`;
  }).join("");
  $("#about-text").innerHTML = `Klangstation ${esc(res.version)}<br>Wiedergabe: MPD · AirPlay: shairport-sync · Spotify Connect: librespot<br>
    Metadaten: <a href="https://musicbrainz.org" target="_blank" rel="noopener">MusicBrainz</a> &amp; <a href="https://coverartarchive.org" target="_blank" rel="noopener">Cover Art Archive</a> ·
    Radio: <a href="https://www.radio-browser.info" target="_blank" rel="noopener">radio-browser.info</a>`;
  loadCountries().then(() => { $("#set-country").value = s.radio_country || ""; });
  btKey = "";
  renderBluetooth();
  renderShares();
  renderAuthState();
  renderCecStatus(res.cec || {});
}

/* Fernseher: CEC-Zustand und Bildschirm */
function renderCecStatus(cec) {
  const el = $("#cec-status");
  let text = "", warn = false;
  if (settings && !settings.cec_enabled) text = "";
  else if (!cec.available) { text = cec.error || "HDMI-CEC ist nicht verfügbar."; warn = true; }
  else if (cec.tv_responds === false) { text = cec.error; warn = true; }
  else text = `CEC aktiv an ${cec.device} (HDMI-Adresse ${cec.physical_address})` +
    (cec.tv_responds ? ", Fernseher antwortet." : ". Ob der Fernseher reagiert, zeigt sich beim nächsten Abspielen.");
  el.textContent = text;
  el.classList.toggle("warn", warn);
}
$("#tv-show").onclick = () => post("/api/tv/show").then(() => toast("Der Bildschirm am HDMI-Ausgang wird geöffnet …"));

/* Netzwerkfreigaben */
function shareScan(scan) {
  if (!scan) return "";
  const total = scan.total || 0;
  const done = Math.min(scan.done || 0, total);
  const known = total > 0;
  const pct = known ? Math.floor((done / total) * 100) : 0;
  const text = known ? `${done.toLocaleString("de-DE")} von ${total.toLocaleString("de-DE")} Titeln (${pct} %)`
                     : scan.total === 0 ? "Keine Musikdateien gefunden" : "wird gezählt …";
  return `
    <div class="share-scan">
      <div class="scanbar${known ? "" : " busy"}"><i style="width:${known ? pct : 100}%"></i></div>
      <small>Wird eingelesen: ${text}. Abspielen von dieser Freigabe ist bis dahin gesperrt.</small>
    </div>`;
}
function renderShares() {
  const list = (settingsRes && settingsRes.shares) || [];
  $("#share-list").innerHTML = list.map((sh) => `
    <div class="share" data-id="${esc(sh.id)}">
      ${ICON("net")}
      <span><b>${esc(sh.name)}</b><small>${sh.type === "nfs" ? "nfs" : "smb"}://${esc(sh.host)}/${esc(sh.path)}${sh.user ? " · " + esc(sh.user) : ""} –
        ${sh.mounted ? `<span class="ok">${sh.scan ? "eingebunden, wird eingelesen" : "eingebunden"}</span>`
                     : `<span class="err">${esc(sh.error || "nicht eingebunden")}</span>`}</small></span>
      <button type="button" class="mini" data-share="rescan"${sh.scan ? " disabled" : ""}>Neu einlesen</button>
      <button type="button" class="mini" data-share="remove">Entfernen</button>
      ${shareScan(sh.scan)}
    </div>`).join("") || '<p class="hint">Noch keine Freigaben eingerichtet.</p>';
}
function shareFormData() {
  const d = {};
  $$("#share-form [data-f]").forEach((el) => { d[el.dataset.f] = el.value; });
  return d;
}
$("#share-form [data-f='type']").addEventListener("change", (ev) => {
  $$("#share-form .smb-only").forEach((el) => { el.hidden = ev.target.value === "nfs"; });
});
$("#share-add").onclick = async () => {
  const btn = $("#share-add");
  btn.disabled = true; btn.textContent = "Wird eingebunden …";
  try {
    const shares = await post("/api/shares/save", shareFormData());
    settingsRes.shares = shares;
    renderShares();
    const added = shares[shares.length - 1];
    if (added && added.mounted) {
      toast(`„${added.name}“ eingebunden. Die Musik wird jetzt eingelesen.`);
      $$("#share-form [data-f]").forEach((el) => { if (el.tagName === "INPUT") el.value = ""; });
    } else if (added) toast(`„${added.name}“: ${added.error || "nicht eingebunden"}`, true);
  } catch (e) { /* Meldung kam schon */ }
  btn.disabled = false; btn.textContent = "Freigabe einbinden";
};
$("#share-list").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-share]");
  if (!b) return;
  const id = b.closest("[data-id]").dataset.id;
  if (b.dataset.share === "remove" && !confirm("Freigabe entfernen? Die Dateien auf dem Server bleiben unberührt.")) return;
  settingsRes.shares = await post("/api/shares/" + b.dataset.share, { id });
  renderShares();
  if (b.dataset.share === "rescan") toast("Freigabe wird neu eingelesen …");
});

/* Zugangsschutz */
function renderAuthState() {
  const on = authInfo.enabled;
  const el = $("#auth-state");
  el.textContent = on
    ? `Geschützt: ${authInfo.scope === "all" ? "die gesamte Oberfläche" : "Optionen, Bluetooth-Kopplung und Freigaben"}.` +
      (authInfo.local ? " (Du bist direkt am Pi angemeldet.)" : "")
    : "Kein Passwort gesetzt. Jeder im Netzwerk kann Klangstation bedienen und einstellen.";
  el.classList.toggle("on", on);
  $("#auth-scope").value = authInfo.scope || "settings";
  $("#auth-remove").hidden = !on;
  $("#auth-logout").hidden = !on || authInfo.local;
  $("#auth-set").textContent = on ? "Passwort ändern" : "Passwort festlegen";
}
$("#auth-set").onclick = async () => {
  const pw = $("#auth-pw").value, pw2 = $("#auth-pw2").value;
  if (pw.length < 6) { toast("Das Passwort muss mindestens 6 Zeichen haben.", true); return; }
  if (pw !== pw2) { toast("Die Passwörter stimmen nicht überein.", true); return; }
  await post("/api/auth/password", { password: pw, scope: $("#auth-scope").value });
  $("#auth-pw").value = $("#auth-pw2").value = "";
  await refreshAuth(); renderAuthState();
  toast("Passwort gespeichert. Andere Geräte müssen sich neu anmelden.");
};
$("#auth-scope").addEventListener("change", async (ev) => {
  if (!authInfo.enabled) return;  // wird mit dem Passwort gespeichert
  await post("/api/auth/password", { scope: ev.target.value });
  await refreshAuth(); renderAuthState();
  toast("Schutzumfang geändert.");
});
$("#auth-remove").onclick = async () => {
  if (!confirm("Zugangsschutz entfernen? Danach kann jeder im Netzwerk alles einstellen.")) return;
  await post("/api/auth/password", { remove: true });
  await refreshAuth(); renderAuthState();
  toast("Zugangsschutz entfernt.");
};
$("#auth-logout").onclick = async () => {
  await post("/api/auth/logout");
  location.reload();
};

/* Bluetooth: Kopplungsfenster und gekoppelte Geräte (live aus dem Zustand) */
let btKey = "";
function renderBluetooth() {
  const bt = (S && S.bluetooth) || {};
  const box = $("#bt-box");
  const enabled = settings && settings.bluetooth_enabled;
  const key = JSON.stringify([bt, enabled]);
  if (key === btKey) return;
  btKey = key;
  if (!enabled) { box.innerHTML = ""; return; }
  if (!bt.available) {
    box.innerHTML = `<p class="hint">${esc(bt.error || "Bluetooth ist nicht verfügbar.")}</p>`;
    return;
  }
  const devices = (bt.devices || []).map((d) => `
    <div class="bt-dev" data-path="${esc(d.path)}">
      ${ICON("bt")}<span><b>${esc(d.name || d.address)}</b><small>${esc(d.address)}${d.connected ? " · verbunden" : ""}</small></span>
      ${d.connected ? '<button type="button" class="mini" data-bt="disconnect">Trennen</button>' : ""}
      <button type="button" class="mini" data-bt="remove">Entfernen</button>
    </div>`).join("");
  box.innerHTML = `
    <div class="bt-head">
      ${bt.pairing
        ? `<button type="button" class="btn primary" data-bt="pairing_off">Kopplung beenden</button>
           <span class="bt-pairing">Sichtbar als „${esc(S.device_name)}“, noch ${bt.pairing_left} s – jetzt am Handy in den Bluetooth-Einstellungen auswählen. Nach dem Koppeln schließt sich das Fenster von selbst.</span>`
        : `<button type="button" class="btn" data-bt="pairing_on">${ICON("bt")}Neues Gerät koppeln (2 Min.)</button>`}
    </div>
    ${!bt.pairing && bt.just_paired
      ? `<p class="bt-done">✓ „${esc(bt.just_paired)}“ wurde gekoppelt. Der Pi ist nicht mehr für neue Geräte sichtbar.</p>` : ""}
    ${devices || '<p class="hint">Noch keine Geräte gekoppelt.</p>'}`;
}

$("#bt-box").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-bt]");
  if (!b) return;
  const action = b.dataset.bt;
  const dev = b.closest("[data-path]");
  if (action === "remove" && !confirm("Gerät entfernen? Es muss danach neu gekoppelt werden.")) return;
  await post("/api/bluetooth/" + action, { path: dev ? dev.dataset.path : "" });
});
// Countdown im Kopplungsfenster auch ohne neue Statusmeldung weiterzählen
setInterval(() => {
  if (currentView === "settings" && S && S.bluetooth && S.bluetooth.pairing && S.bluetooth.pairing_left > 0) {
    S.bluetooth.pairing_left -= 1;
    renderBluetooth();
  }
}, 1000);

$("#settings-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const data = {};
  for (const el of f.elements) {
    // nur echte Einstellungen; Passwort- und Freigabefelder haben eigene Knöpfe
    if (!el.name || (el.name !== "output" && !(el.name in settings))) continue;
    if (el.type === "checkbox") data[el.name] = el.checked;
    else if (el.type === "radio") { if (el.checked) data.output = el.value || null; }
    else if (el.name === "spotify_bitrate" || el.name === "cec_standby_minutes") data[el.name] = +el.value;
    else data[el.name] = el.value;
  }
  $("#save-msg").textContent = "Wird übernommen…";
  try {
    const res = await post("/api/settings", data);
    settings = res.settings;
    fillSettings(res);
    $("#save-msg").textContent = "Gespeichert.";
  } catch (e) {
    $("#save-msg").textContent = "";
  }
});

/* =========================================================== Schlummer-Timer & Wecker */
const DAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
let alarmList = [], alarmEdit = null;

function sleepLeft() {
  const tm = (S && S.timers) || {};
  if (!tm.sleep || !tm.sleep.until) return null;
  // Restzeit gegen die Serveruhr gerechnet: die Uhr des Browsers darf abweichen
  return Math.max(0, tm.sleep.until - tm.ts - (performance.now() - receivedAt) / 1000);
}
function timerText() {
  const tm = (S && S.timers) || {};
  if (tm.sleep) return tm.sleep.mode === "track" ? "Schlummern nach diesem Titel" : "Schlummern " + fmt(sleepLeft());
  if (tm.next_alarm) return "Wecker " + tm.next_alarm.day + " " + tm.next_alarm.time;
  return "";
}
function statusRight() {
  const n = S.now || {};
  $("#status-right").textContent = [KIND_LABEL[n.kind] || "", n.kind === "radio" ? "Live" : "", timerText()]
    .filter(Boolean).join(" · ");
}
setInterval(() => {
  if (!(S && S.timers && S.timers.sleep)) return;
  statusRight();
  if (!$("#timer-modal").hidden) $("#sleep-state").textContent = sleepText();
}, 1000);
function sleepText() {
  const sl = S.timers.sleep;
  return !sl ? "Aus." : sl.mode === "track" ? "Hält nach dem laufenden Titel an."
    : `Noch ${fmt(sleepLeft())} – die letzten 30 Sekunden wird leiser geblendet.`;
}

function alarmDays(a) {
  if (!a.days.length) return "einmalig";
  if (a.days.length === 7) return "täglich";
  if (a.days.join() === "0,1,2,3,4") return "Mo–Fr";
  if (a.days.join() === "5,6") return "Sa, So";
  return a.days.map((d) => DAY_NAMES[d]).join(", ");
}
function alarmLabel(t) {
  return t.kind === "station" ? t.name || "Webradio" : t.kind === "playlist" ? "Liste „" + t.name + "“" : "Bibliothek (Zufall)";
}

function renderTimers() {
  const tm = (S && S.timers) || {};
  const sl = tm.sleep;
  $$("#sleep-seg button").forEach((b) => {
    const m = b.dataset.min;
    b.classList.toggle("on", sl ? (sl.mode === "track" ? m === "track" : +m === sl.minutes) : m === "0");
  });
  $("#sleep-state").textContent = sleepText();
  const next = tm.next_alarm;
  $("#alarm-list").innerHTML = alarmList.map((a) => `
    <div class="alarm${a.enabled ? "" : " off"}${next && next.id === a.id ? " next" : ""}" data-id="${esc(a.id)}">
      <label class="switch" title="Ein/aus"><input type="checkbox" data-al="toggle"${a.enabled ? " checked" : ""}></label>
      <b class="al-time">${esc(a.time)}</b>
      <span class="al-info">${esc(alarmDays(a))} · ${esc(alarmLabel(a.target))}<small>Lautstärke ${a.volume} %${a.stop_after ? " · aus nach " + (a.stop_after >= 60 ? a.stop_after / 60 + " h" : a.stop_after + " min") : ""}</small></span>
      <button type="button" class="mini" data-al="test" title="Jetzt auslösen">Test</button>
      <button type="button" class="mini" data-al="edit">Ändern</button>
      <button type="button" class="mini" data-al="remove" title="Löschen">${ICON("x")}</button>
    </div>`).join("") || '<p class="hint">Noch kein Wecker.</p>';
}

async function fillAlarmTargets(selected) {
  const sel = $("#al-target");
  let lists = [];
  try { lists = await api("/api/playlists", { quiet: true }); } catch (e) { /* MPD startet noch */ }
  const st = favs();
  sel.innerHTML =
    (st.length ? `<optgroup label="Radio-Favoriten">${st.map((f, i) => `<option value="s${i}">${esc(f.name)}</option>`).join("")}</optgroup>` : "") +
    (lists.length ? `<optgroup label="Wiedergabelisten">${lists.map((p) => `<option value="p:${esc(p.name)}">${esc(p.name)}</option>`).join("")}</optgroup>` : "") +
    '<option value="lib">Bibliothek (Zufall)</option>';
  if (selected) {
    let v = "lib";
    if (selected.kind === "station") {
      let i = st.findIndex((f) => f.url === selected.url);
      if (i < 0) {  // Sender ist kein Favorit mehr: trotzdem auswählbar lassen
        sel.insertAdjacentHTML("afterbegin", `<option value="cur">${esc(selected.name || "Webradio")}</option>`);
        v = "cur";
      } else v = "s" + i;
    } else if (selected.kind === "playlist") v = "p:" + selected.name;
    sel.value = v;
  }
}
function alarmTarget() {
  const v = $("#al-target").value;
  if (v === "cur") return alarmEdit.target;
  if (v.startsWith("s")) {
    const f = favs()[+v.slice(1)];
    return { kind: "station", url: f.url, name: f.name, uuid: f.uuid, favicon: f.favicon };
  }
  if (v.startsWith("p:")) return { kind: "playlist", name: v.slice(2) };
  return { kind: "library" };
}

function editAlarm(a) {
  alarmEdit = a;
  $("#al-time").value = a ? a.time : "07:00";
  const days = a ? a.days : [0, 1, 2, 3, 4];
  $$("#al-days button").forEach((b) => b.classList.toggle("on", days.includes(+b.dataset.d)));
  $("#al-vol").value = a ? a.volume : 30;
  $("#al-stop").value = String(a ? a.stop_after : 60);
  $("#al-save").textContent = a ? "Änderung speichern" : "Wecker anlegen";
  $("#al-cancel").hidden = !a;
  showVol();
  return fillAlarmTargets(a && a.target);
}
function showVol() { const r = $("#al-vol"); $("#al-vol-v").textContent = r.value + " %"; paintRange(r); }

$("#al-days").innerHTML = DAY_NAMES.map((d, i) => `<button type="button" data-d="${i}">${d}</button>`).join("");
$("#al-days").onclick = (ev) => { const b = ev.target.closest("button"); if (b) b.classList.toggle("on"); };
$("#al-vol").oninput = showVol;
$("#al-cancel").onclick = () => editAlarm(null);

$("#b-timer").onclick = async () => {
  $("#timer-modal").hidden = false;
  if (!settings) await loadSettings(true);
  try { alarmList = (await api("/api/alarms")).alarms; } catch (e) { /* Meldung kam schon */ }
  await editAlarm(null);
  renderTimers();
};
$("#timer-close").onclick = () => { $("#timer-modal").hidden = true; };
$("#timer-modal").addEventListener("click", (ev) => { if (ev.target.id === "timer-modal") $("#timer-modal").hidden = true; });

$("#sleep-seg").onclick = async (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  const m = b.dataset.min;
  try {
    S.timers = Object.assign({}, S.timers, await post("/api/sleep", { minutes: m === "track" ? "track" : +m }));
    receivedAt = performance.now();
    render();
  } catch (e) { /* Meldung kam schon */ }
};

$("#alarm-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const data = {
    time: $("#al-time").value, target: alarmTarget(), volume: +$("#al-vol").value, stop_after: +$("#al-stop").value,
    days: $$("#al-days button.on").map((b) => +b.dataset.d), enabled: true,
  };
  if (alarmEdit) data.id = alarmEdit.id;
  try {
    const res = await post("/api/alarms/save", data);
    alarmList = res.alarms;
    S.timers = Object.assign({}, S.timers, { next_alarm: res.next_alarm });
    toast(res.next_alarm ? `Nächster Wecker: ${res.next_alarm.day} ${res.next_alarm.time}` : "Wecker gespeichert");
    await editAlarm(null);
    render();
  } catch (e) { /* Meldung kam schon */ }
});

$("#alarm-list").addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-al]");
  if (!el) return;
  const id = el.closest("[data-id]").dataset.id;
  const a = alarmList.find((x) => x.id === id);
  const act = el.dataset.al;
  if (act === "edit") { await editAlarm(a); $("#al-time").focus(); return; }
  if (act === "remove" && !confirm(`Wecker ${a.time} löschen?`)) return;
  if (act === "test" && !confirm("Wecker jetzt auslösen? Er spielt sofort, beginnend leise.")) return;
  try {
    const res = await post("/api/alarms/" + act, { id, enabled: el.checked });
    alarmList = res.alarms;
    S.timers = Object.assign({}, S.timers, { next_alarm: res.next_alarm });
    if (alarmEdit && alarmEdit.id === id && act === "remove") await editAlarm(null);
    render();
  } catch (e) { /* Meldung kam schon */ }
});

/* =========================================================== Visualisierung */
const vis = {
  canvas: $("#vis"),
  modes: ["Balken", "Ambience", "Aus"],
  mode: 0,
  playing: false,
  visible: true,
  level: 0,
  peaks: [],
};
try { vis.mode = Math.max(0, vis.modes.indexOf(localStorage.getItem("ks-vis") || "Balken")); } catch (e) { /* privat */ }
$("#vis-switch").textContent = vis.modes[vis.mode];
$("#vis-switch").onclick = () => {
  vis.mode = (vis.mode + 1) % vis.modes.length;
  $("#vis-switch").textContent = vis.modes[vis.mode];
  try { localStorage.setItem("ks-vis", vis.modes[vis.mode]); } catch (e) { /* privat */ }
};

// Der Ton läuft auf dem Gerät, nicht im Browser. Die Animation ist daher eine
// Stimmungsanzeige im Stil alter Player und keine echte Spektralanalyse.
function drawVis(t) {
  requestAnimationFrame(drawVis);
  if (!vis.visible || document.hidden) return;
  const c = vis.canvas;
  const w = c.clientWidth, h = c.clientHeight;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (c.width !== w * dpr || c.height !== h * dpr) { c.width = w * dpr; c.height = h * dpr; }
  const g = c.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  vis.level += ((vis.playing ? 1 : 0) - vis.level) * 0.04;
  const L = vis.level;
  const s = t / 1000;

  g.fillStyle = "rgba(0,0,0,0.35)";
  g.fillRect(0, 0, w, h);
  if (vis.mode === 2) { g.fillStyle = "#000"; g.fillRect(0, 0, w, h); return; }

  if (vis.mode === 0) {
    const n = Math.max(16, Math.floor(w / 18));
    const bw = w / n;
    const base = h * 0.78;
    const beat = 0.6 + 0.4 * Math.pow(Math.max(0, Math.sin(s * 7.6)), 6);
    for (let i = 0; i < n; i++) {
      const x = i / n;
      const v = (0.55 * Math.abs(Math.sin(s * 1.7 + i * 0.45)) + 0.3 * Math.abs(Math.sin(s * 3.9 + i * 1.3)) +
        0.25 * Math.abs(Math.sin(s * 0.8 + i * 0.12))) * (1.1 - x * 0.55) * beat;
      const bh = Math.max(2, v * base * 0.75 * L + 2);
      const grad = g.createLinearGradient(0, base - bh, 0, base);
      grad.addColorStop(0, "#c6f1ff");
      grad.addColorStop(0.35, "#2fb4ff");
      grad.addColorStop(1, "#0b3c8c");
      g.fillStyle = grad;
      g.fillRect(i * bw + 2, base - bh, bw - 4, bh);
      g.fillStyle = "rgba(47,180,255,0.18)";
      g.fillRect(i * bw + 2, base + 3, bw - 4, bh * 0.35);
      vis.peaks[i] = Math.max((vis.peaks[i] || 0) - 1.2, bh);
      g.fillStyle = "#e8f8ff";
      g.fillRect(i * bw + 2, base - vis.peaks[i] - 4, bw - 4, 2);
    }
  } else {
    const cx = w / 2, cy = h * 0.42;
    const r = Math.min(w, h) * 0.32;
    g.globalCompositeOperation = "lighter";
    for (let k = 0; k < 3; k++) {
      g.beginPath();
      for (let a = 0; a <= Math.PI * 2 + 0.01; a += 0.04) {
        const wob = 1 + (0.12 + 0.25 * L) * Math.sin(a * (3 + k) + s * (0.9 + k * 0.4)) * Math.sin(s * 0.7 + k);
        const x = cx + Math.cos(a + s * 0.2 * (k + 1)) * r * wob * (0.6 + k * 0.25);
        const y = cy + Math.sin(a + s * 0.2 * (k + 1)) * r * wob * (0.6 + k * 0.25) * 0.75;
        a === 0 ? g.moveTo(x, y) : g.lineTo(x, y);
      }
      g.strokeStyle = ["rgba(111,211,255,.55)", "rgba(80,120,255,.45)", "rgba(180,90,255,.35)"][k];
      g.lineWidth = 2 + L * 2;
      g.stroke();
    }
    g.globalCompositeOperation = "source-over";
  }
}
requestAnimationFrame(drawVis);

/* =========================================================== Start */
(async () => {
  await refreshAuth();
  if (authInfo.enabled && authInfo.scope === "all" && !authInfo.logged_in) {
    await requireLogin("Klangstation ist mit einem Passwort geschützt.", true);
  }
  loadSettings(true);
  showView(location.hash.slice(1) || "now");
  connect();
})();
