(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ICONS = { Clear: "☀️", Clouds: "☁️", Rain: "🌧️", Drizzle: "🌦️", Thunderstorm: "⛈️", Snow: "❄️", Mist: "🌫️", Fog: "🌫️" };
  const icon = (c, day = true) => (!day && c === "Clear" ? "🌙" : ICONS[c] || "🌡️");
  const r0 = (v) => (v == null ? "–" : Math.round(v));
  const year = $("year"); if (year) year.textContent = new Date().getFullYear();

  // Telegram links: deep-link to a specific action when set.
  let bot = "skymatee_bot";
  function setBot(name) {
    bot = name;
    document.querySelectorAll(".tg-link").forEach((a) => {
      a.href = `https://t.me/${bot}` + (a.dataset.start ? `?start=${a.dataset.start}` : "");
    });
  }

  // Live weather demo
  const card = $("wx");
  async function lookup(q) {
    if (!card) return;
    card.innerHTML = `<div class="wx-muted">Checking the latest readings for ${esc(q)}…</div>`;
    try {
      const r = await fetch(`/site/api/weather?q=${encodeURIComponent(q)}`);
      const d = await r.json();
      if (!r.ok) { card.innerHTML = `<div class="wx-muted">${esc(d.error || "Something went wrong.")}</div>`; return; }
      const m = d.measured;
      const badge = m
        ? `<span class="wx-badge">● Measured at ${esc(m.station)} · ${m.distance_km} km · ${m.age_minutes < 90 ? m.age_minutes + " min" : Math.round(m.age_minutes / 60) + " h"} ago</span>`
        : `<span class="wx-badge est">Model estimate · no station nearby</span>`;
      const days = d.days.map((x) => {
        const name = new Date(x.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" });
        return `<div class="wx-day"><b>${esc(name)}</b><div class="i">${icon(x.condition)}</div>${r0(x.max)}° <span style="color:var(--muted)">${r0(x.min)}°</span></div>`;
      }).join("");
      card.innerHTML = `
        <div class="wx-top">
          <div><div class="wx-place">${esc(d.place)}${d.country ? ", " + esc(d.country) : ""}</div>
            <div class="wx-desc">${esc(d.description)}</div></div>
          <div class="wx-icon">${icon(d.condition, d.is_day)}</div>
        </div>
        <div class="wx-temp">${r0(d.temperature)}°C</div>
        <div class="wx-meta">
          <span>Feels like ${r0(d.feels_like)}°</span><span>Humidity ${r0(d.humidity)}%</span>
          <span>Wind ${d.wind_speed == null ? "–" : d.wind_speed.toFixed(1)} m/s</span>
        </div>
        <div style="margin-bottom:14px">${badge}</div>
        <div class="wx-days">${days}</div>`;
    } catch (e) {
      card.innerHTML = `<div class="wx-muted">Couldn't reach the weather service. Please try again.</div>`;
    }
  }
  const form = $("search");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("q").value.trim();
      if (q) lookup(q.slice(0, 100));
    });
    lookup("Baku");
  }

  // Service stats
  fetch("/v1/status").then((r) => r.json()).then((s) => {
    const obs = s.observations || {};
    if ($("s-readings")) $("s-readings").textContent = obs.readings ? obs.readings.toLocaleString() : "—";
    if ($("s-stations")) $("s-stations").textContent = obs.stations ? obs.stations.toLocaleString() : "—";
    const until = s.offline_ready_until ? new Date(s.offline_ready_until) : null;
    if ($("s-forecast")) $("s-forecast").textContent = until ? Math.max(1, Math.round((until - Date.now()) / 86400000)) + " days" : "10 days";
  }).catch(() => {});

  fetch("/site/api/info").then((r) => r.json()).then((i) => {
    if (i.bot) setBot(i.bot);
    if ($("stars") && i.premium_stars) $("stars").textContent = i.premium_stars;
  }).catch(() => setBot(bot));

  // Pricing tabs
  const API_FEATURES = {
    free: ["Current weather & forecasts", "5-day daily forecasts", "7 days of history"],
    starter: ["Everything in Free", "10-day forecasts", "90 days of history"],
    pro: ["Everything in Starter", "Full year of measured history", "Higher rate limits"],
    business: ["Everything in Pro", "Highest volumes", "Priority support"],
  };
  let apiLoaded = false;
  async function loadApiPlans() {
    if (apiLoaded) return;
    apiLoaded = true;
    const d = await fetch("/v1/plans").then((r) => r.json());
    const order = ["free", "starter", "pro", "business"];
    $("tab-api").innerHTML = order.filter((k) => d.plans[k]).map((k) => {
      const p = d.plans[k];
      return `<div class="plan${k === "pro" ? " featured" : ""}">
        <h3>${k[0].toUpperCase() + k.slice(1)}</h3>
        <div class="price">$${p.price_usd_month}<small> / month</small></div>
        <div class="sub">${p.daily.toLocaleString()} requests/day · ${p.per_minute.toLocaleString()}/min</div>
        <ul>${API_FEATURES[k].map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
        <a class="btn ${k === "pro" ? "btn-primary" : "btn-ghost"}" href="/docs">${k === "free" ? "Read the docs" : "Get started"}</a>
      </div>`;
    }).join("");
  }
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    const api = b.dataset.tab === "api";
    $("tab-personal").hidden = api;
    $("tab-api").hidden = !api;
    $("api-note").hidden = !api;
    if (api) loadApiPlans();
  }));
})();
