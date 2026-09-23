import { useCallback, useEffect, useRef, useState } from "react"
import { useReducedMotion } from "motion/react"

import { Cta, Developers, Faq, Features, Measured, Pricing, Stats, TelegramBot } from "@/components/site/sections"
import { Footer } from "@/components/site/footer"
import { Header } from "@/components/site/header"
import { Privacy, Terms } from "@/components/site/legal"
import { DashboardSkeleton, SavedCities, SearchBar, WeatherDashboard } from "@/components/weather/dashboard"
import { ForegroundRain, Sky, type SkyScene } from "@/components/weather/sky"
import { getLanguage, translate } from "@/lib/i18n"
import { exactPlace, fetchDashboard, WeatherError, type Dashboard, type Units } from "@/lib/weather"

const DEFAULT_CITY = "Baku"
const CONDITIONS = ["Clear", "Clouds", "Rain", "Drizzle", "Thunderstorm", "Snow", "Mist", "Fog"] as const

/** ?sky=rain or ?sky=clear-night previews a background scene regardless of the real weather. */
function previewSky(): SkyScene | null {
  const raw = new URLSearchParams(location.search).get("sky")?.toLowerCase()
  if (!raw) return null
  const [name, time] = raw.split("-")
  const condition = CONDITIONS.find((c) => c.toLowerCase() === name)
  return condition ? { condition, isDay: time !== "night" } : null
}

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null
    return v && allowed.includes(v) ? v : fallback
  } catch {
    return fallback
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage unavailable (private mode); the preference just isn't remembered */
  }
}

/**
 * `gps` marks the visitor's own position: it is never written to the address bar.
 * `label` is the name the visitor actually picked (a search result or a saved place), which is kept as shown:
 * coordinates alone would be named after the nearest city, turning "Budapest XI. kerület" into "Budapest".
 */
type Query = { q?: string; lat?: number; lon?: number; gps?: boolean; label?: string }

const CITY_PATH = /^\/weather\/([a-z0-9-]{1,60})$/

/** A place from a shared link (/weather/baku or ?q=…), or null when the address has none. */
function linkedQuery(): Query | null {
  const city = CITY_PATH.exec(location.pathname)
  if (city) return { q: city[1].replace(/-/g, " ") }
  const p = new URLSearchParams(location.search)
  const lat = Number(p.get("lat")), lon = Number(p.get("lon"))
  if (p.has("lat") && p.has("lon") && Number.isFinite(lat) && Number.isFinite(lon)) return { lat, lon }
  const q = (p.get("q") ?? "").slice(0, 100)
  return q ? { q } : null
}

const LAST_KEY = "skymate-last"   // last place shown, so a returning visitor sees it immediately
const CACHE_KEY = "skymate-dash"  // last dashboard, shown instantly while fresh data loads
const CACHE_MAX_AGE = 3 * 3600_000

const queryKey = (q: Query) =>
  q.lat !== undefined && q.lon !== undefined ? `${q.lat.toFixed(2)},${q.lon.toFixed(2)}` : (q.q ?? "").toLowerCase()

/** Never waits for anything: a shared link, else the last place viewed, else the default city. */
function initialQuery(): Query {
  const linked = linkedQuery()
  if (linked) return linked
  try {
    const last = JSON.parse(localStorage.getItem(LAST_KEY) ?? "null") as Query | null
    if (last && (last.q || (Number.isFinite(last.lat) && Number.isFinite(last.lon)))) return last
  } catch { /* storage unavailable */ }
  return { q: DEFAULT_CITY }
}

function cachedDashboard(query: Query): Dashboard | null {
  try {
    const c = JSON.parse(localStorage.getItem(CACHE_KEY) ?? "null") as { key: string; at: number; data: Dashboard } | null
    return c && c.key === queryKey(query) && Date.now() - c.at < CACHE_MAX_AGE ? c.data : null
  } catch {
    return null
  }
}

function remember(query: Query, data: Dashboard) {
  try {
    localStorage.setItem(LAST_KEY, JSON.stringify(query))
    localStorage.setItem(CACHE_KEY, JSON.stringify({ key: queryKey(query), at: Date.now(), data }))
  } catch { /* storage full or unavailable: the next visit just loads normally */ }
}

function syncUrl(query: Query) {
  const url = new URL(location.href)
  // Leaving a city page (/weather/baku) for another place: back to the plain address
  if (CITY_PATH.test(url.pathname) && query.q?.replace(/\s+/g, "-").toLowerCase() !== CITY_PATH.exec(url.pathname)![1]) {
    url.pathname = "/"
  }
  for (const k of ["q", "lat", "lon"]) url.searchParams.delete(k)
  if (query.q && query.q !== DEFAULT_CITY) url.searchParams.set("q", query.q)
  if (!query.gps && query.lat !== undefined && query.lon !== undefined) {
    url.searchParams.set("lat", query.lat.toFixed(3))
    url.searchParams.set("lon", query.lon.toFixed(3))
  }
  history.replaceState(null, "", url)
}

function Home({ units, paused, setCondition, setSkyActive, bot, stars }: {
  units: Units
  paused: boolean
  setSkyActive: (active: boolean) => void
  setCondition: (c: SkyScene) => void
  bot: string
  stars: number
}) {
  const [query, setQuery] = useState<Query>(initialQuery)
  const [data, setData] = useState<Dashboard | null>(() => cachedDashboard(query))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  const errorRef = useRef<HTMLParagraphElement>(null)
  const topRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = topRef.current
    if (!el || !("IntersectionObserver" in window)) return
    const io = new IntersectionObserver(([e]) => setSkyActive(e.isIntersecting))
    io.observe(el)
    return () => { io.disconnect(); setSkyActive(true) }
  }, [setSkyActive])

  /** Asks for the visitor's position. On entry this runs in the background: weather is already on screen,
   * and the page switches to the visitor's own location only if they allow it. */
  const locate = useCallback((onEntry: boolean) => {
    if (!("geolocation" in navigator)) {
      if (!onEntry) setError(translate(getLanguage(), "error.noGeolocation"))
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const next: Query = { lat: pos.coords.latitude, lon: pos.coords.longitude, gps: true }
        // Skip the reload when the visitor is already looking at (almost) the same spot
        setQuery((q) => (onEntry && q.gps && queryKey(q) === queryKey(next) ? q : next))
      },
      () => { if (!onEntry) setError(translate(getLanguage(), "error.locationBlocked")) },
      { timeout: 10_000, maximumAge: 600_000 },
    )
  }, [])

  useEffect(() => {
    if (!linkedQuery()) locate(true)
  }, [locate])

  // Saved weather is on screen from the first frame: show its sky too, instead of the neutral loading sky
  useEffect(() => {
    if (data) setCondition({ condition: data.now.condition, isDay: data.now.is_day, cloudCover: data.now.cloud_cover })
    // only once, for the cached dashboard; fresh data updates the sky in the fetch below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const ctrl = new AbortController()
    setBusy(true)
    setError(null)
    fetchDashboard(query, ctrl.signal)
      .then((fresh) => {
        // Keep the name the visitor chose, not the nearest city the coordinates resolve to
        const d = query.label ? { ...fresh, location: { ...fresh.location, name: query.label } } : fresh
        setData(d)
        remember(query, d)
        if (query.gps && !query.label && d.location.name_source !== "osm") nameNeighbourhood(query, d, ctrl.signal)
        setCondition({ condition: d.now.condition, isDay: d.now.is_day, cloudCover: d.now.cloud_cover })
        syncUrl(query)
        document.title = translate(getLanguage(), "page.title", { city: d.location.name })
      })
      .catch((e) => {
        if ((e as Error).name === "AbortError") return
        setError(e instanceof WeatherError ? e.message : translate(getLanguage(), "error.generic"))
      })
      .finally(() => { if (!ctrl.signal.aborted) setBusy(false) })
    return () => ctrl.abort()
  }, [query, setCondition])

  /** For the visitor's own position: replace the city name with the neighbourhood, looked up by their browser. */
  const nameNeighbourhood = useCallback(async (q: Query, d: Dashboard, signal: AbortSignal) => {
    const place = await exactPlace(q.lat!, q.lon!, d.location.name, signal)
    if (!place) return
    const named: Dashboard = { ...d, location: { ...d.location, name: place.name, detail: place.detail,
      country: place.country || d.location.country, name_source: "osm" } }
    setData((prev) => (prev === d ? named : prev))
    remember(q, named)
    document.title = translate(getLanguage(), "page.title", { city: named.location.name })
  }, [])

  useEffect(() => { if (error) errorRef.current?.focus() }, [error])

  const search = (
    <div>
      <SearchBar busy={busy} onSelect={(p) => setQuery({ lat: p.lat, lon: p.lon, label: p.name })} onLocate={() => locate(false)} />
      <SavedCities
        current={data ? { name: data.location.name, country: data.location.country, lat: data.location.lat, lon: data.location.lon } : null}
        onSelect={(p) => setQuery({ lat: p.lat, lon: p.lon, label: p.name })}
      />
      <p ref={errorRef} tabIndex={-1} role="alert" aria-live="polite"
        className={error ? "mt-2 rounded-xl bg-red-500/15 px-3 py-2 text-sm text-red-100 outline-none" : "sr-only"}>
        {error ?? ""}
      </p>
    </div>
  )

  return (
    <>
      <h1 className="sr-only">{translate(getLanguage(), "aria.liveWeather")}{data ? `: ${data.location.name}` : ""}</h1>
      <div ref={topRef} className="space-y-6">
        {data ? <div key={data.location.name} className="sky-fade-in"><WeatherDashboard data={data} units={units} search={search} onScene={setCondition} /></div> : (
          error ? (
            <div className="rounded-3xl border border-white/10 bg-slate-950/75 p-4">
              {search}
              <button type="button" onClick={() => setQuery({ ...query })}
                className="mt-3 rounded-full bg-white px-5 py-2 text-sm font-medium text-slate-900 outline-none hover:bg-sky-100 focus-visible:ring-2 focus-visible:ring-sky-300">
                {translate(getLanguage(), "error.retry")}
              </button>
            </div>
          ) : <DashboardSkeleton />
        )}
        <Stats />
      </div>
      <div className="mt-24 space-y-24 sm:mt-32 sm:space-y-32" data-paused={paused || undefined}>
        <Features />
        <Measured />
        <Pricing bot={bot} stars={stars} />
        <TelegramBot bot={bot} />
        <Developers />
        <Faq />
        <Cta bot={bot} />
      </div>
    </>
  )
}

export default function App() {
  const reduceMotion = useReducedMotion()
  const [units, setUnitsState] = useState<Units>(() => readStored("skymate-units", ["metric", "imperial"] as const, "metric"))
  const [pausedPref, setPausedPref] = useState(() => readStored("skymate-paused", ["1", "0"] as const, "0") === "1")
  // No scene until real data arrives: a neutral sky, then a cross-fade into the actual weather.
  const [sky, setSky] = useState<SkyScene | null>(null)
  const [info, setInfo] = useState({ bot: "skymatee_bot", stars: 150 })
  const [skyActive, setSkyActive] = useState(true)
  const paused = pausedPref || !!reduceMotion
  const skyPreview = previewSky()
  const path = location.pathname.replace(/\/+$/, "") || "/"

  useEffect(() => {
    fetch("/site/api/info").then((r) => r.json()).then((d) => setInfo({ bot: d.bot, stars: d.premium_stars })).catch(() => {})
  }, [])

  const setUnits = (u: Units) => { setUnitsState(u); store("skymate-units", u) }
  const setPaused = (p: boolean) => { setPausedPref(p); store("skymate-paused", p ? "1" : "0") }

  let page
  if (path === "/terms") page = <Terms />
  else if (path === "/privacy") page = <Privacy />
  else page = <Home units={units} paused={paused} setCondition={setSky} setSkyActive={setSkyActive} bot={info.bot} stars={info.stars} />

  return (
    <>
      <a href="#main" className="sr-only z-50 rounded-lg bg-white px-4 py-2 text-slate-900 focus:not-sr-only focus:fixed focus:left-4 focus:top-4">
        {translate(getLanguage(), "aria.skip")}
      </a>
      <Sky scene={skyPreview ?? sky} paused={paused} active={skyActive} />
      <ForegroundRain scene={skyPreview ?? sky} paused={paused} active={skyActive} />
      <Header units={units} setUnits={setUnits} paused={pausedPref} setPaused={setPaused} bot={info.bot} />
      <main id="main" tabIndex={-1} className="mx-auto max-w-7xl px-3 pt-4 pb-24 outline-none sm:px-6 sm:pt-8
        pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))]">
        {page}
      </main>
      <Footer bot={info.bot} />
    </>
  )
}
