import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import {
  AlertTriangle, CalendarDays, Clock, Droplet, Droplets, Eye, LocateFixed, MapPin, Radio, RotateCcw, Search, Sun, Thermometer, Wind,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { WeatherIcon } from "@/components/weather/weather-icon"
import { cn } from "@/lib/utils"
import {
  compass, countryName, daySummary, feelsNote, fmt, searchPlaces, summary, title, uvCategory,
  type Dashboard as Data, type Place, type Units,
} from "@/lib/weather"

// Two equal columns that end on the same line; the sky shows between the cards.
const panel = "grid gap-4 lg:grid-cols-2"

function CardTitle({ icon, children, id }: { icon: ReactNode; children: ReactNode; id?: string }) {
  return (
    <h3 id={id} className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-white/60">
      <span aria-hidden="true" className="text-white/70 [&_svg]:size-4">{icon}</span>
      {children}
    </h3>
  )
}

function Tile({ icon, label, value, note }: { icon: ReactNode; label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="flex h-full min-h-32 min-w-0 flex-col gap-1 rounded-2xl border border-white/15 bg-slate-950/30 p-4 backdrop-blur-[3px] [text-shadow:0_1px_2px_rgb(0_0_0/0.35)] transition-colors hover:border-white/20 sm:min-h-36">
      <CardTitle icon={icon}>{label}</CardTitle>
      <div className="mt-1 text-3xl font-medium tabular-nums text-white sm:text-4xl">{value}</div>
      {note && <p className="mt-auto text-pretty text-[13px] leading-snug text-white/65">{note}</p>}
    </div>
  )
}

export function SearchBar({ onSelect, onLocate, busy }: {
  onSelect: (place: Place) => void
  onLocate: () => void
  busy: boolean
}) {
  const id = useId()
  const listId = `${id}-list`
  const [text, setText] = useState("")
  const [places, setPlaces] = useState<Place[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [status, setStatus] = useState<"idle" | "loading" | "none">("idle")
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const q = text.trim()
    if (q.length < 2) {
      setPlaces([])
      setStatus("idle")
      return
    }
    const ctrl = new AbortController()
    setStatus("loading")
    const t = setTimeout(() => {
      searchPlaces(q, ctrl.signal)
        .then((p) => { setPlaces(p); setActive(0); setStatus(p.length ? "idle" : "none") })
        .catch(() => { if (!ctrl.signal.aborted) setStatus("idle") })
    }, 180)
    return () => { clearTimeout(t); ctrl.abort() }
  }, [text])

  const choose = (p: Place | undefined) => {
    if (!p) return
    onSelect(p)
    setText("")
    setPlaces([])
    setOpen(false)
    inputRef.current?.blur()
  }

  const showList = open && text.trim().length >= 2 && (places.length > 0 || status === "none")

  return (
    <form
      role="search"
      className="relative z-30"
      onSubmit={(e) => { e.preventDefault(); choose(places[active]) }}
    >
      <div className="flex items-center gap-2 rounded-full border border-white/15 bg-slate-950/30 p-1.5 pl-4 backdrop-blur-[3px] focus-within:ring-2 focus-within:ring-sky-300/60">
        <MapPin aria-hidden="true" className="size-4 shrink-0 text-white/70" />
        <label htmlFor={id} className="sr-only">Search for a city</label>
        <Input
          ref={inputRef}
          id={id}
          name="q"
          value={text}
          onChange={(e) => { setText(e.target.value.slice(0, 100)); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" && places.length) { e.preventDefault(); setOpen(true); setActive((a) => (a + 1) % places.length) }
            else if (e.key === "ArrowUp" && places.length) { e.preventDefault(); setActive((a) => (a - 1 + places.length) % places.length) }
            else if (e.key === "Enter") { e.preventDefault(); choose(places[active]) }
            else if (e.key === "Escape") setOpen(false)
          }}
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && places[active] ? `${listId}-${active}` : undefined}
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="search"
          placeholder="Search a city, e.g. Hanoi…"
          className="h-9 min-w-0 flex-1 border-0 bg-transparent px-0 text-[15px] text-white shadow-none placeholder:text-white/50 focus-visible:ring-0 dark:bg-transparent"
        />
        <Button
          type="button"
          size="icon"
          variant="ghost"
          onClick={onLocate}
          aria-label="Use my location"
          title="Use my location"
          className="size-9 shrink-0 rounded-full text-white/80 hover:bg-white/15 hover:text-white"
        >
          <LocateFixed aria-hidden="true" />
        </Button>
        <Button type="submit" disabled={busy || !places.length} className="h-9 shrink-0 rounded-full bg-white px-4 text-slate-900 hover:bg-sky-100">
          <Search aria-hidden="true" className="sm:hidden" />
          <span className="max-sm:sr-only">{busy ? "Loading…" : "Search"}</span>
        </Button>
      </div>

      <ul id={listId} role="listbox" aria-label="Matching places"
        className={cn("absolute inset-x-0 top-full mt-2 overflow-hidden rounded-2xl border border-white/10 bg-slate-950/95 py-1.5 shadow-2xl",
          !showList && "hidden")}>
        {status === "none" && !places.length ? (
          <li className="px-4 py-3 text-sm text-white/60">No matching places. Check the spelling.</li>
        ) : places.map((p, i) => (
          <li key={`${p.name}-${p.lat}-${p.lon}`} id={`${listId}-${i}`} role="option" aria-selected={i === active}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => choose(p)}
            onMouseEnter={() => setActive(i)}
            className={cn("flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm", i === active ? "bg-white/10" : "")}>
            <MapPin aria-hidden="true" className="size-4 shrink-0 text-white/50" />
            <span className="min-w-0 truncate text-white" translate="no">{p.name}</span>
            <span className="ml-auto shrink-0 text-xs text-white/50">{countryName(p.country)}</span>
          </li>
        ))}
      </ul>
    </form>
  )
}

function UvBar({ value }: { value: number | null }) {
  const pct = Math.min(Math.max((value ?? 0) / 11, 0), 1) * 100
  return (
    <div className="relative mt-4 h-2 rounded-full bg-[linear-gradient(90deg,#3ddc84_0%,#d8e93c_30%,#ffb300_55%,#ff3d3d_78%,#c026d3_100%)]">
      <span
        className="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-slate-900 bg-white shadow"
        style={{ left: `${pct}%` }}
      />
    </div>
  )
}

function Compass({ deg }: { deg: number | null }) {
  const rotate = deg == null ? 0 : (deg + 180) % 360
  return (
    <svg viewBox="0 0 120 120" className="size-28 shrink-0 sm:size-32" role="img" aria-label={deg == null ? "Wind direction unknown" : `Wind from ${compass(deg)}`}>
      <circle cx="60" cy="60" r="56" fill="none" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" />
      <circle cx="60" cy="60" r="44" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="1" />
      {Array.from({ length: 36 }, (_, i) => (
        <line key={i} x1="60" y1="7" x2="60" y2={i % 9 === 0 ? 15 : 11} stroke="rgba(255,255,255,0.4)" strokeWidth="1"
          transform={`rotate(${i * 10} 60 60)`} />
      ))}
      {[["N", 60, 26], ["E", 95, 64], ["S", 60, 100], ["W", 25, 64]].map(([l, x, y]) => (
        <text key={l as string} x={x as number} y={y as number} textAnchor="middle" fontSize="11" fill="white" fontWeight="600">{l}</text>
      ))}
      {deg != null && (
        <g transform={`rotate(${rotate} 60 60)`}>
          <path d="M60 26 L66 60 L60 56 L54 60 Z" fill="white" />
          <path d="M60 94 L54 60 L60 64 L66 60 Z" fill="rgba(255,255,255,0.45)" />
        </g>
      )}
      <circle cx="60" cy="60" r="3.5" fill="#0b1220" stroke="white" strokeWidth="1.5" />
    </svg>
  )
}

export function DashboardSkeleton() {
  return (
    <div className={panel} aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading weather…</span>
      <div className="order-1 space-y-4">
        <Skeleton className="h-12 rounded-full bg-slate-900/30" />
        <Skeleton className="h-[22rem] rounded-3xl bg-slate-900/30" />
      </div>
      <div className="order-2 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:order-3 lg:col-span-2">
        {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-36 rounded-2xl bg-slate-900/30" />)}
      </div>
      <div className="order-3 space-y-4 lg:order-2">
        <Skeleton className="h-52 rounded-3xl bg-slate-900/30" />
        <div className="grid gap-4 sm:grid-cols-2"><Skeleton className="h-52 rounded-3xl bg-slate-900/30" /><Skeleton className="h-52 rounded-3xl bg-slate-900/30" /></div>
      </div>
    </div>
  )
}

type Selection = { kind: "now" } | { kind: "hour"; index: number } | { kind: "day"; index: number }

type View = {
  forecast: boolean
  heading: string
  condition: Data["now"]["condition"]
  isDay: boolean
  temp: number | null
  range: string | null
  title: string
  summary: string
  feels: { value: string; note: ReactNode }
  precip: { value: string; note: ReactNode }
  visibility: { value: string; note: string }
  humidity: { value: string; note: ReactNode }
  uv: { value: number | null; note: ReactNode }
  wind: { speed: number | null; gust: number | null; direction: number | null; label: string }
}

function visibilityNote(m: number | null | undefined, lowest = false) {
  if (m == null) return "No visibility reading nearby."
  if (m >= 10000) return lowest ? "Clear all day." : "Perfectly clear view."
  const text = m >= 4000 ? "slightly hazy." : "reduced visibility, take care."
  return lowest ? `At its lowest: ${text}` : text[0].toUpperCase() + text.slice(1)
}

function dayName(date: string, index: number, tz: string) {
  if (index === 0) return "Today"
  if (index === 1) return "Tomorrow"
  return new Intl.DateTimeFormat(undefined, { weekday: "long", timeZone: tz }).format(new Date(`${date}T12:00:00Z`))
}

function buildView(data: Data, sel: Selection, units: Units): View {
  const tz = data.location.timezone
  const now = data.now
  const humidity = (h: number | null | undefined, dew: number | null | undefined, when: string) => ({
    value: h == null ? "–" : `${Math.round(h)}%`,
    note: dew == null ? undefined : <>The dew point is {fmt.temp(dew, units)} {when}.</>,
  })

  if (sel.kind === "hour") {
    const h = data.hourly[sel.index]
    const w = fmt.speed(h.wind_speed, units)
    return {
      forecast: true,
      heading: `${new Intl.DateTimeFormat(undefined, { weekday: "short", timeZone: tz }).format(new Date(h.time))} · ${fmt.time(h.time, tz)}`,
      condition: h.condition,
      isDay: h.is_day,
      temp: h.temperature == null ? null : fmt.tempValue(h.temperature, units),
      range: null,
      title: title(h),
      summary: `At ${fmt.time(h.time, tz)}, expect ${h.description || title(h).toLowerCase()} and ${fmt.temp(h.temperature, units)}` +
        (h.wind_speed != null ? `, with wind at ${w.value} ${w.unit}${h.wind_direction != null ? ` from the ${compass(h.wind_direction)}` : ""}.` : "."),
      feels: { value: fmt.temp(h.feels_like, units), note: feelsNote(h) },
      precip: {
        value: `${fmt.rain(h.precipitation_rate, units)}/h`,
        note: (h.precipitation_rate ?? 0) > 0 ? "Expected rate at this hour." : "No rain expected at this hour.",
      },
      visibility: { value: fmt.distance(h.visibility, units), note: visibilityNote(h.visibility) },
      humidity: humidity(h.humidity, h.dew_point, "at this hour"),
      uv: { value: h.uv_index, note: (h.uv_index ?? 0) >= 3 ? "Use sun protection at this hour." : "No sun protection needed at this hour." },
      wind: { speed: h.wind_speed, gust: h.wind_gust, direction: h.wind_direction, label: "Wind" },
    }
  }

  if (sel.kind === "day") {
    const d = data.daily[sel.index]
    const name = dayName(d.date, sel.index, tz)
    return {
      forecast: sel.index > 0,
      heading: `${name} · ${fmt.dayMonth(d.date, tz)}`,
      condition: d.condition,
      isDay: true,
      temp: d.max == null ? null : fmt.tempValue(d.max, units),
      range: `H ${fmt.temp(d.max, units)} · L ${fmt.temp(d.min, units)}`,
      title: title({ condition: d.condition, is_day: true, description: d.description }),
      summary: daySummary(d, name, units, d.uv_max ?? null),
      feels: { value: fmt.temp(d.feels_like_max, units), note: "The warmest it will feel during the day." },
      precip: {
        value: fmt.rain(d.precipitation, units),
        note: (d.precipitation ?? 0) >= 1 ? "Expected during the day. Keep an umbrella handy." : "Total expected during the day.",
      },
      visibility: { value: fmt.distance(d.visibility_min, units), note: visibilityNote(d.visibility_min, true) },
      humidity: humidity(d.humidity, d.dew_point, "on average"),
      uv: {
        value: d.uv_max ?? null,
        note: (d.uv_max ?? 0) >= 3
          ? <>Peak {fmt.number(d.uv_max ?? 0)} ({uvCategory(d.uv_max ?? null)}). Use sun protection around midday.</>
          : "No sun protection needed.",
      },
      wind: { speed: d.wind_max ?? null, gust: d.gust_max ?? null, direction: d.wind_direction ?? null, label: "Max Wind" },
    }
  }

  return {
    forecast: false,
    heading: "",
    condition: now.condition,
    isDay: now.is_day,
    temp: now.temperature == null ? null : fmt.tempValue(now.temperature, units),
    range: null,
    title: title(now),
    summary: summary(data, units),
    feels: { value: fmt.temp(now.feels_like, units), note: feelsNote(now) },
    precip: {
      value: fmt.rain(data.precipitation.today_mm, units),
      note: <>Today · {fmt.rain(data.precipitation.next_24h_mm, units)} expected in the next 24&nbsp;h</>,
    },
    visibility: { value: fmt.distance(now.visibility, units), note: visibilityNote(now.visibility) },
    humidity: humidity(now.humidity, now.dew_point, "right now"),
    uv: {
      value: now.uv_index,
      note: data.uv.protect_until
        ? <>Use sun protection until {fmt.time(data.uv.protect_until, tz)}.</>
        : (data.uv.max_today ?? 0) >= 3
          ? <>Today’s peak: {fmt.number(data.uv.max_today ?? 0)} ({uvCategory(data.uv.max_today)}). Use sun protection around midday.</>
          : "No sun protection needed today.",
    },
    wind: { speed: now.wind_speed, gust: now.wind_gust, direction: now.wind_direction, label: "Wind" },
  }
}

// Light glass: mostly see-through so the live sky stays visible; a soft text shadow keeps text readable.
const card = "rounded-3xl border border-white/15 bg-slate-950/30 backdrop-blur-[3px] [text-shadow:0_1px_2px_rgb(0_0_0/0.35)] shadow-[0_12px_40px_-18px_rgba(0,0,0,0.7)]"
const choice = "flex w-[4.75rem] flex-col items-center rounded-2xl px-2 py-3 outline-none transition-colors sm:w-[5.25rem] focus-visible:ring-2 focus-visible:ring-sky-300"

export function WeatherDashboard({ data, units, search }: { data: Data; units: Units; search: ReactNode }) {
  const tz = data.location.timezone
  const [sel, setSel] = useState<Selection>({ kind: "now" })
  const [tab, setTab] = useState<"hourly" | "daily">("hourly")
  const heroRef = useRef<HTMLElement>(null)
  const hourly = data.hourly.filter((h) => new Date(h.time).getTime() >= Date.now() - 90 * 60 * 1000)
  const firstHour = data.hourly.length - hourly.length
  const view = buildView(data, sel, units)
  const wind = fmt.speed(view.wind.speed, units)
  const gust = fmt.speed(view.wind.gust, units)
  const viewKey = sel.kind === "now" ? "now" : `${sel.kind}-${sel.index}`

  const select = (next: Selection) => {
    setSel(next)
    // On phones the summary sits above the forecast lists: bring it into view so the change is visible.
    const hero = heroRef.current
    if (hero && hero.getBoundingClientRect().bottom < 120) {
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches
      hero.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" })
    }
  }

  return (
    <div className={panel}>
      {/* Left column: search and the selected hour or day (or now) */}
      <div className="order-1 flex min-w-0 flex-col gap-4">
        {search}
        <section ref={heroRef} aria-labelledby="now-title" aria-live="polite"
          className={cn(card, "relative flex-1 scroll-mt-24 overflow-hidden p-5 sm:p-7")}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="flex min-w-0 items-center gap-1.5 text-sm text-white/80">
              <MapPin aria-hidden="true" className="size-4 shrink-0" />
              <span className="truncate" translate="no">{data.location.name}{data.location.country ? `, ${data.location.country}` : ""}</span>
            </p>
            {sel.kind !== "now" ? (
              <button type="button" onClick={() => setSel({ kind: "now" })}
                className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-xs font-medium text-white outline-none transition-colors hover:bg-white/20 focus-visible:ring-2 focus-visible:ring-sky-300">
                <RotateCcw aria-hidden="true" className="size-3.5" />
                Back to Now
              </button>
            ) : data.measured ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-400/15 px-2.5 py-1 text-xs font-medium text-emerald-200">
                <Radio aria-hidden="true" className="size-3.5" />
                Measured {fmt.age(data.measured.age_minutes)}
              </span>
            ) : (
              <span className="rounded-full bg-sky-400/15 px-2.5 py-1 text-xs font-medium text-sky-200">Model estimate</span>
            )}
          </div>

          <div key={viewKey} className="mt-6 flex flex-col items-center text-center animate-in fade-in slide-in-from-bottom-1 duration-300 sm:mt-8">
            <p className={cn("mb-3 rounded-full px-3 py-1 text-xs font-medium tracking-wide",
              view.heading ? "bg-sky-400/15 text-sky-100" : "invisible")}>
              {view.heading ? <>{view.forecast ? "Forecast · " : ""}{view.heading}</> : "Now"}
            </p>
            <WeatherIcon condition={view.condition} isDay={view.isDay} className="size-14 sm:size-16" />
            <p className="mt-2 text-[5.5rem] leading-none font-light tracking-tight text-white tabular-nums sm:text-[7rem]">
              {view.temp == null ? "–" : view.temp}
              <span aria-hidden="true">°</span>
              <span className="sr-only">{units === "imperial" ? "degrees Fahrenheit" : "degrees Celsius"}</span>
            </p>
            {view.range && <p className="mt-1 text-sm tabular-nums text-white/70">{view.range}</p>}
            <h2 id="now-title" className="mt-2 text-balance text-3xl font-medium text-white sm:text-4xl">{view.title}</h2>
            <p className="mt-4 max-w-md text-pretty text-sm leading-relaxed text-white/80 sm:text-[15px]">{view.summary}</p>
            {sel.kind === "now" && data.measured && (
              <p className="mt-3 text-xs text-white/55">
                Temperature measured at <span translate="no">{data.measured.station}</span>, {fmt.number(data.measured.distance_km, 1)}&nbsp;km away
              </p>
            )}
          </div>

          {sel.kind === "now" && data.alerts.length > 0 && (
            <ul className="mt-6 space-y-2" aria-label="Weather warnings">
              {data.alerts.map((a) => (
                <li key={a.event + a.start}
                  className={cn("flex items-center gap-2 rounded-xl px-3 py-2 text-sm",
                    a.severity === "severe" ? "bg-red-500/20 text-red-100" : "bg-amber-400/15 text-amber-100")}>
                  <AlertTriangle aria-hidden="true" className="size-4 shrink-0" />
                  <span className="min-w-0"><strong className="font-medium">{a.event}</strong> · {a.start === a.end ? <>around {fmt.time(a.start, tz)}</> : <>{fmt.time(a.start, tz)}–{fmt.time(a.end, tz)}</>}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* Detail tiles in one row across the dashboard (2×2 on phones, right under the summary) */}
      <div className="order-2 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:order-3 lg:col-span-2">
        <Tile icon={<Thermometer />} label="Feels like" value={view.feels.value} note={view.feels.note} />
        <Tile icon={<Droplet />} label="Precipitation" value={view.precip.value} note={view.precip.note} />
        <Tile icon={<Eye />} label="Visibility" value={view.visibility.value} note={view.visibility.note} />
        <Tile icon={<Droplets />} label="Humidity" value={view.humidity.value} note={view.humidity.note} />
      </div>

      {/* Right column: hourly or 10-day (toggle), UV, wind. Choosing an hour or a day updates the summary. */}
      <div className="order-3 flex min-w-0 flex-col gap-4 lg:order-2">
        <section aria-label="Forecast" className={cn(card, "p-4 sm:p-5")}>
          <div className="flex items-center justify-between gap-3">
            <CardTitle id="forecast-title" icon={tab === "hourly" ? <Clock /> : <CalendarDays />}>
              {tab === "hourly" ? "Hourly Forecast" : `${data.daily.length}-Day Forecast`}
            </CardTitle>
            <div role="tablist" aria-label="Forecast range" className="flex shrink-0 rounded-full bg-white/10 p-1">
              {([["hourly", "Hourly"], ["daily", `${data.daily.length} Days`]] as const).map(([key, label]) => (
                <button key={key} type="button" role="tab" id={`tab-${key}`} aria-selected={tab === key} aria-controls="forecast-panel"
                  onClick={() => setTab(key)}
                  className={cn("rounded-full px-3 py-1 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-300",
                    tab === key ? "bg-white text-slate-900" : "text-white/75 hover:text-white")}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-3 border-t border-white/10" />
          <div id="forecast-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
            <ol key={tab} role="list" aria-label={tab === "hourly" ? "Hourly forecast, scroll horizontally" : "Daily forecast, scroll horizontally"}
              className="scroll-row mt-3 flex snap-x snap-mandatory gap-2 overflow-x-auto p-0.5 pb-2 animate-in fade-in duration-300">
              {tab === "hourly" ? hourly.map((h, i) => {
                const selected = i === 0 ? sel.kind === "now" : sel.kind === "hour" && sel.index === firstHour + i
                return (
                  <li key={h.time} className="shrink-0 snap-start">
                    <button type="button" aria-pressed={selected}
                      onClick={() => select(i === 0 ? { kind: "now" } : { kind: "hour", index: firstHour + i })}
                      className={cn(choice, "gap-2", selected ? "bg-white/20 ring-1 ring-white/25" : "hover:bg-white/10")}>
                      <span className="whitespace-nowrap text-sm text-white/75">{i === 0 ? "Now" : fmt.hour(h.time, tz)}</span>
                      <span className="text-2xl font-medium tabular-nums text-white">{fmt.temp(h.temperature, units)}</span>
                      <WeatherIcon condition={h.condition} isDay={h.is_day} className="size-6" />
                    </button>
                  </li>
                )
              }) : data.daily.map((d, i) => {
                const selected = sel.kind === "day" && sel.index === i
                return (
                  <li key={d.date} className="shrink-0 snap-start">
                    <button type="button" aria-pressed={selected} onClick={() => select({ kind: "day", index: i })}
                      className={cn(choice, "gap-1", selected ? "bg-white/20 ring-1 ring-white/25" : "hover:bg-white/10")}>
                      <span className="whitespace-nowrap text-sm text-white/80">{i === 0 ? "Today" : fmt.weekday(d.date, tz)}</span>
                      <span className="text-xs text-white/50 tabular-nums">{fmt.dayMonth(d.date, tz)}</span>
                      <span className="mt-1 text-2xl font-medium tabular-nums text-white">{fmt.temp(d.max, units)}</span>
                      <span className="text-xs tabular-nums text-white/55">{fmt.temp(d.min, units)}</span>
                      <WeatherIcon condition={d.condition} className="mt-1 size-6" />
                    </button>
                  </li>
                )
              })}
            </ol>
          </div>
        </section>

        <div className="grid flex-1 gap-4 sm:grid-cols-2">
          <section aria-labelledby="uv-title" className={cn(card, "flex min-w-0 flex-col p-4 sm:p-5")}>
            <CardTitle id="uv-title" icon={<Sun />}>{sel.kind === "day" ? "UV Index · Peak" : "UV Index"}</CardTitle>
            <p className="mt-4 text-4xl font-medium tabular-nums text-white">{view.uv.value == null ? "–" : fmt.number(view.uv.value, 0)}</p>
            <p className="text-lg text-white/90">{uvCategory(view.uv.value)}</p>
            <UvBar value={view.uv.value} />
            <p className="mt-auto pt-4 text-[13px] text-white/65">{view.uv.note}</p>
          </section>

          <section aria-labelledby="wind-title" className={cn(card, "min-w-0 p-4 sm:p-5")}>
            <CardTitle id="wind-title" icon={<Wind />}>{view.wind.label}</CardTitle>
            <div className="mt-3 flex items-center justify-between gap-3">
              <dl className="min-w-0 flex-1 divide-y divide-white/10">
                <div className="flex items-baseline gap-2 pb-3">
                  <dt className="order-2 text-sm leading-tight text-white/70"><span className="block uppercase">{wind.unit}</span>Wind</dt>
                  <dd className="order-1 text-4xl font-medium tabular-nums text-white">{wind.value}</dd>
                </div>
                <div className="flex items-baseline gap-2 pt-3">
                  <dt className="order-2 text-sm leading-tight text-white/70"><span className="block uppercase">{gust.unit}</span>Gusts</dt>
                  <dd className="order-1 text-4xl font-medium tabular-nums text-white">{gust.value}</dd>
                </div>
              </dl>
              <Compass deg={view.wind.direction} />
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
