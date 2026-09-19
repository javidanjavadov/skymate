import { useCallback, useEffect, useRef, useState } from "react"
import { useReducedMotion } from "motion/react"

import { Cta, DesktopApp, Developers, Faq, Features, Measured, Pricing, Stats } from "@/components/site/sections"
import { Footer } from "@/components/site/footer"
import { Header } from "@/components/site/header"
import { Privacy, Terms } from "@/components/site/legal"
import { DashboardSkeleton, SearchBar, WeatherDashboard } from "@/components/weather/dashboard"
import { ForegroundRain, Sky } from "@/components/weather/sky"
import { fetchDashboard, WeatherError, type Dashboard, type Units } from "@/lib/weather"

const DEFAULT_CITY = "Baku"
const CONDITIONS = ["Clear", "Clouds", "Rain", "Drizzle", "Thunderstorm", "Snow", "Mist", "Fog"] as const

/** ?sky=rain or ?sky=clear-night previews a background scene regardless of the real weather. */
function previewSky(): { condition: Dashboard["now"]["condition"]; isDay: boolean } | null {
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

function initialQuery() {
  const p = new URLSearchParams(location.search)
  const lat = Number(p.get("lat")), lon = Number(p.get("lon"))
  if (p.has("lat") && p.has("lon") && Number.isFinite(lat) && Number.isFinite(lon)) return { lat, lon }
  return { q: (p.get("q") ?? "").slice(0, 100) || DEFAULT_CITY }
}

function syncUrl(query: { q?: string; lat?: number; lon?: number }) {
  const url = new URL(location.href)
  for (const k of ["q", "lat", "lon"]) url.searchParams.delete(k)
  if (query.q && query.q !== DEFAULT_CITY) url.searchParams.set("q", query.q)
  if (query.lat !== undefined && query.lon !== undefined) {
    url.searchParams.set("lat", query.lat.toFixed(3))
    url.searchParams.set("lon", query.lon.toFixed(3))
  }
  history.replaceState(null, "", url)
}

function Home({ units, paused, setCondition, setSkyActive, bot, stars }: {
  units: Units
  paused: boolean
  setSkyActive: (active: boolean) => void
  setCondition: (c: { condition: Dashboard["now"]["condition"]; isDay: boolean; cloudCover?: number | null }) => void
  bot: string
  stars: number
}) {
  const [query, setQuery] = useState(initialQuery)
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

  useEffect(() => {
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

  const locate = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setError("Your browser can’t share your location. Search for your city instead.")
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => setQuery({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => setError("Location access was blocked. Allow it in your browser, or search for your city."),
      { timeout: 10_000, maximumAge: 600_000 },
    )
  }, [])

  const search = (
    <div>
      <SearchBar busy={busy} defaultValue={query.q ?? ""} onSearch={(q) => setQuery({ q })} onLocate={locate} />
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
        {data ? <WeatherDashboard data={data} units={units} search={search} /> : (
          error ? (
            <div className="rounded-3xl border border-white/10 bg-slate-950/50 p-4 backdrop-blur-xl">
              {search}
              <button type="button" onClick={() => setQuery({ ...query })}
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
  const [sky, setSky] = useState<{ condition: Dashboard["now"]["condition"]; isDay: boolean; cloudCover?: number | null }>({ condition: "Clouds", isDay: true })
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
      <Sky condition={skyPreview?.condition ?? sky.condition} isDay={skyPreview?.isDay ?? sky.isDay} cloudCover={sky.cloudCover} paused={paused} active={skyActive} />
      <ForegroundRain condition={skyPreview?.condition ?? sky.condition} paused={paused} active={skyActive} />
      <Header units={units} setUnits={setUnits} paused={pausedPref} setPaused={setPaused} bot={info.bot} />
      <main id="main" tabIndex={-1} className="mx-auto max-w-7xl px-3 pt-4 pb-24 outline-none sm:px-6 sm:pt-8
        pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))]">
        {page}
      </main>
      <Footer bot={info.bot} />
    </>
  )
}
