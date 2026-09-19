import { useCallback, useEffect, useRef, useState } from "react"
import { useReducedMotion } from "motion/react"

import { Cta, DesktopApp, Developers, Faq, Features, Measured, Pricing, Stats } from "@/components/site/sections"
import { Footer } from "@/components/site/footer"
import { Header } from "@/components/site/header"
import { Privacy, Terms } from "@/components/site/legal"
import { DashboardSkeleton, SearchBar, WeatherDashboard } from "@/components/weather/dashboard"
import { ForegroundRain, Sky, type SkyScene } from "@/components/weather/sky"
import { fetchDashboard, WeatherError, type Dashboard, type Units } from "@/lib/weather"

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

/** `gps` marks the visitor's own position: it is never written to the address bar. */
type Query = { q?: string; lat?: number; lon?: number; gps?: boolean }

/** A place from a shared link, or null to ask the visitor for their location first. */
function initialQuery(): Query | null {
  const p = new URLSearchParams(location.search)
  const lat = Number(p.get("lat")), lon = Number(p.get("lon"))
  if (p.has("lat") && p.has("lon") && Number.isFinite(lat) && Number.isFinite(lon)) return { lat, lon }
  const q = (p.get("q") ?? "").slice(0, 100)
  return q ? { q } : null
}

function syncUrl(query: Query) {
  const url = new URL(location.href)
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
  const [query, setQuery] = useState<Query | null>(initialQuery)
  const [data, setData] = useState<Dashboard | null>(null)
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

  /** Asks for the visitor's position. On first entry a refusal (or no answer) falls back to the default city. */
  const locate = useCallback((onEntry: boolean) => {
    const fallback = () => setQuery((q) => q ?? { q: DEFAULT_CITY })
    if (!("geolocation" in navigator)) {
      if (onEntry) fallback()
      else setError("Your browser can’t share your location. Search for your city instead.")
      return
    }
    // Someone who ignores the permission prompt still gets weather; accepting later switches to their location.
    const timer = onEntry ? setTimeout(fallback, 8000) : undefined
    navigator.geolocation.getCurrentPosition(
      (pos) => { clearTimeout(timer); setQuery({ lat: pos.coords.latitude, lon: pos.coords.longitude, gps: true }) },
      () => {
        clearTimeout(timer)
        if (onEntry) fallback()
        else setError("Location access was blocked. Allow it in your browser, or search for your city.")
      },
      { timeout: 10_000, maximumAge: 600_000 },
    )
  }, [])

  useEffect(() => {
    if (!initialQuery()) locate(true)
  }, [locate])

  useEffect(() => {
    if (!query) return
    const ctrl = new AbortController()
    setBusy(true)
    setError(null)
    fetchDashboard(query, ctrl.signal)
      .then((d) => {
        setData(d)
        setCondition({ condition: d.now.condition, isDay: d.now.is_day, cloudCover: d.now.cloud_cover })
        syncUrl(query)
        document.title = `${d.location.name} Weather — SkyMate`
      })
      .catch((e) => {
        if ((e as Error).name === "AbortError") return
        setError(e instanceof WeatherError ? e.message : "Something went wrong. Try again in a moment.")
      })
      .finally(() => { if (!ctrl.signal.aborted) setBusy(false) })
    return () => ctrl.abort()
  }, [query, setCondition])

  useEffect(() => { if (error) errorRef.current?.focus() }, [error])

  const search = (
    <div>
      <SearchBar busy={busy} onSelect={(p) => setQuery({ lat: p.lat, lon: p.lon })} onLocate={() => locate(false)} />
      <p ref={errorRef} tabIndex={-1} role="alert" aria-live="polite"
        className={error ? "mt-2 rounded-xl bg-red-500/15 px-3 py-2 text-sm text-red-100 outline-none" : "sr-only"}>
        {error ?? ""}
      </p>
    </div>
  )

  return (
    <>
      <h1 className="sr-only">SkyMate live weather{data ? ` for ${data.location.name}` : ""}</h1>
      <div ref={topRef} className="space-y-6">
        {data ? <div key={data.location.name} className="sky-fade-in"><WeatherDashboard data={data} units={units} search={search} /></div> : (
          error ? (
            <div className="rounded-3xl border border-white/10 bg-slate-950/75 p-4">
              {search}
              <button type="button" onClick={() => setQuery({ ...(query ?? { q: DEFAULT_CITY }) })}
                className="mt-3 rounded-full bg-white px-5 py-2 text-sm font-medium text-slate-900 outline-none hover:bg-sky-100 focus-visible:ring-2 focus-visible:ring-sky-300">
                Try Again
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
        <DesktopApp bot={bot} />
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
        Skip to Content
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
