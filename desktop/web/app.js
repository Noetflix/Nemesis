"use strict";

// URL de l'API : fournie par app.py via le pont pywebview, avec repli sur la query
// string (mode navigateur) puis sur le défaut local.
const params = new URLSearchParams(location.search);
const DEFAULT_API = "http://127.0.0.1:8787";
let API = (params.get("api") || DEFAULT_API).replace(/\/$/, "");

const REFRESH_MS = 15000;
let timer = null;

async function resolveApi() {
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.config) {
      const cfg = await window.pywebview.api.config();
      if (cfg && cfg.api) return cfg.api.replace(/\/$/, "");
    }
  } catch (e) {
    /* repli ci-dessous */
  }
  return (params.get("api") || DEFAULT_API).replace(/\/$/, "");
}

const $ = (id) => document.getElementById(id);

// Icône et libellé par type d'évènement.
const KINDS = {
  command: ["⌨️", (e) => `Commande <b>!${e.name}</b>`],
  command_error: ["⚠️", (e) => `Erreur sur <b>!${e.name || "?"}</b>`],
  game_alert: ["🎮", (e) => `${e.name} en game (<b>${e.detail || "?"}</b>)`],
  match_notif: ["🏁", (e) => `Fin de partie — ${e.name} · ${e.win ? "Victoire ✅" : "Défaite ❌"}`],
  bet_result: ["🎲", (e) => `Pari clôturé · ${e.win ? "Victoire" : "Défaite"}`],
};

async function getJSON(path) {
  const res = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function fmtDuree(s) {
  if (s == null) return "";
  s = Math.floor(s);
  const j = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (j) return `${j}j ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

function tempsRelatif(ts) {
  const d = (Date.now() - ts * 1000) / 1000;
  if (d < 60) return "à l'instant";
  if (d < 3600) return `il y a ${Math.floor(d / 60)} min`;
  if (d < 86400) return `il y a ${Math.floor(d / 3600)} h`;
  return `il y a ${Math.floor(d / 86400)} j`;
}

function setOnline(online) {
  const s = $("status");
  s.className = `pill ${online ? "pill--online" : "pill--offline"}`;
  s.textContent = online ? "En ligne" : "Hors ligne";
  $("offline").classList.toggle("hidden", online);
}

function renderKpis(o) {
  const wr = o.tracked_wins + o.tracked_losses > 0;
  const tiles = [
    { v: o.commands_total, l: "Commandes", sub: `+${o.commands_today} aujourd'hui` },
    { v: o.games_tracked, l: "Alertes en game" },
    { v: o.matches_notified, l: "Parties notifiées" },
    { v: o.bets_total, l: "Paris", sub: o.bet_participants ? `${o.bet_participants} parieurs` : "" },
    { v: wr ? `${o.tracked_winrate}%` : "—", l: "Winrate suivi", sub: wr ? `${o.tracked_wins}V ${o.tracked_losses}D` : "" },
    { v: o.total_runs, l: "Démarrages" },
  ];
  $("kpis").innerHTML = tiles
    .map(
      (t) => `<div class="kpi"><div class="kpi__value">${t.v}</div>
      <div class="kpi__label">${t.l}</div>
      ${t.sub ? `<div class="kpi__sub">${t.sub}</div>` : ""}</div>`
    )
    .join("");
}

function renderActivity(points) {
  const max = Math.max(1, ...points.map((p) => p.count));
  const total = points.reduce((a, p) => a + p.count, 0);
  $("activity-total").textContent = `${total} sur ${points.length} jours`;
  $("activity").innerHTML = points
    .map((p) => {
      const h = Math.round((p.count / max) * 100);
      const jj = p.date.slice(8, 10);
      return `<div class="chart__bar" data-empty="${p.count ? 0 : 1}"
        style="height:${Math.max(3, h)}%" title="${p.date} · ${p.count}"><span>${jj}</span></div>`;
    })
    .join("");
}

function renderCommands(cmds) {
  const box = $("commands");
  if (!cmds.length) {
    box.innerHTML = `<div class="empty">Aucune commande enregistrée pour l'instant.</div>`;
    return;
  }
  const max = Math.max(...cmds.map((c) => c.count));
  box.innerHTML = cmds
    .slice(0, 8)
    .map(
      (c) => `<div class="bar__row">
        <div class="bar__name">!${c.name}</div>
        <div class="bar__track"><div class="bar__fill" style="width:${(c.count / max) * 100}%"></div></div>
        <div class="bar__val">${c.count}</div></div>`
    )
    .join("");
}

function renderPlayers(players) {
  const box = $("players");
  if (!players.length) {
    box.innerHTML = `<div class="empty">Aucune partie suivie pour l'instant.</div>`;
    return;
  }
  box.innerHTML = players
    .slice(0, 8)
    .map((p) => {
      const total = p.wins + p.losses || 1;
      return `<div class="player">
        <div class="player__name">${p.name}</div>
        <div class="player__wr">${p.winrate}%</div>
        <div class="player__track">
          <div class="player__win" style="width:${(p.wins / total) * 100}%"></div>
          <div class="player__loss" style="width:${(p.losses / total) * 100}%"></div>
        </div>
        <div class="player__vd">${p.wins}V · ${p.losses}D</div></div>`;
    })
    .join("");
}

function renderEvents(events) {
  const box = $("events");
  if (!events.length) {
    box.innerHTML = `<li class="empty">Rien à afficher — le bot n'a encore rien fait.</li>`;
    return;
  }
  box.innerHTML = events
    .slice(0, 12)
    .map((e) => {
      const [ico, txt] = KINDS[e.kind] || ["•", () => e.kind];
      return `<li><span class="feed__ico">${ico}</span>
        <span class="feed__txt">${txt(e)}</span>
        <span class="feed__time">${tempsRelatif(e.ts)}</span></li>`;
    })
    .join("");
}

async function refresh() {
  $("refresh").classList.add("spin");
  try {
    const [overview, commands, activity, players, events] = await Promise.all([
      getJSON("/api/overview"),
      getJSON("/api/commands"),
      getJSON("/api/activity?days=14"),
      getJSON("/api/players"),
      getJSON("/api/events?limit=12"),
    ]);
    setOnline(true);
    $("uptime").textContent = overview.uptime_seconds != null ? `uptime ${fmtDuree(overview.uptime_seconds)}` : "";
    renderKpis(overview);
    renderActivity(activity);
    renderCommands(commands);
    renderPlayers(players);
    renderEvents(events);
  } catch (err) {
    setOnline(false);
  } finally {
    setTimeout(() => $("refresh").classList.remove("spin"), 600);
  }
}

function tick() {
  $("clock").textContent = new Date().toLocaleTimeString("fr-FR");
}

async function init() {
  API = await resolveApi();
  $("api-label").textContent = API;
  $("offline-url").textContent = API;
  $("refresh").addEventListener("click", refresh);
  setInterval(tick, 1000);
  tick();
  refresh();
  timer = setInterval(refresh, REFRESH_MS);
}

// Attendre le pont pywebview s'il arrive vite ; sinon démarrer (mode navigateur).
if (window.pywebview) {
  init();
} else {
  let lance = false;
  const go = () => {
    if (!lance) {
      lance = true;
      init();
    }
  };
  window.addEventListener("pywebviewready", go);
  setTimeout(go, 350);
}
