import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import {
  AlertTriangle, CalendarDays, Clock, Droplet, Droplets, Eye, LocateFixed, MapPin, Radio, RotateCcw, Search,
  ShieldCheck,
  Star, Sun, Sunrise, Thermometer, Wind, X,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import type { SkyScene } from "@/components/weather/sky"
import { WeatherIcon } from "@/components/weather/weather-icon"
import { getLanguage, localeOf, translate, useT } from "@/lib/i18n"
import { isSaved, removeSaved, samePlace, toggleSaved, useSavedPlaces, type Saved } from "@/lib/saved-places"
import { cn } from "@/lib/utils"
import {
  alertName, compass, countryName, daySummary, feelsNote, fetchBrief, fmt, searchPlaces, summary, title, uvCategory,
  type Brief, type Dashboard as Data, type Hour, type Place, type Units,
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
    <div className="flex h-full min-w-0 flex-col gap-2 rounded-2xl border border-white/15 bg-slate-950/30 p-4 [text-shadow:0_1px_2px_rgb(0_0_0/0.35)] transition-colors hover:border-white/20">
      <CardTitle icon={icon}>{label}</CardTitle>
      <div className="text-3xl font-medium tabular-nums text-white sm:text-4xl">{value}</div>
      {note && <p className="text-pretty text-[13px] leading-snug text-white/65">{note}</p>}
    </div>
  )
}

export function SearchBar({ onSelect, onLocate, busy }: {
  onSelect: (place: Place) => void
  onLocate: () => void
  busy: boolean
}) {
  const { t } = useT()
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
      <div className="flex items-center gap-2 rounded-full border border-white/15 bg-slate-950/30 p-1.5 pl-4 focus-within:ring-2 focus-within:ring-sky-300/60">
        <MapPin aria-hidden="true" className="size-4 shrink-0 text-white/70" />
        <label htmlFor={id} className="sr-only">{t("search.label")}</label>
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
          placeholder={t("search.placeholder")}
          className="h-9 min-w-0 flex-1 border-0 bg-transparent px-0 text-[15px] text-white shadow-none placeholder:text-white/50 focus-visible:ring-0 dark:bg-transparent"
        />
        <Button
          type="button"
          size="icon"
          variant="ghost"
          onClick={onLocate}
          aria-label={t("search.locate")}
          title={t("search.locate")}
          className="size-9 shrink-0 rounded-full text-white/80 hover:bg-white/15 hover:text-white"
        >
          <LocateFixed aria-hidden="true" />
        </Button>
        <Button type="submit" disabled={busy || !places.length} className="h-9 shrink-0 rounded-full bg-white px-4 text-slate-900 hover:bg-sky-100">
          <Search aria-hidden="true" className="sm:hidden" />
          <span className="max-sm:sr-only">{busy ? t("search.loading") : t("search.button")}</span>
        </Button>
      </div>

      <ul id={listId} role="listbox" aria-label={t("search.list")}
        className={cn("absolute inset-x-0 top-full mt-2 overflow-hidden rounded-2xl border border-white/10 bg-slate-950/95 py-1.5 shadow-2xl",
          !showList && "hidden")}>
        {status === "none" && !places.length ? (
          <li className="px-4 py-3 text-sm text-white/60">{t("search.none")}</li>
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

/** Saved places as small cards: name, current temperature and sky, so they can be compared at a glance. */
export function SavedCities({ current, units, onSelect }: {
  current: Saved | null
  units: Units
  onSelect: (place: Saved) => void
}) {
  const { t } = useT()
  const saved = useSavedPlaces()
  const [brief, setBrief] = useState<Record<string, Brief>>({})

  const points = saved.map((p) => `${p.lat.toFixed(3)},${p.lon.toFixed(3)}`).join(";")
  useEffect(() => {
    if (!points) return
    const ctrl = new AbortController()
    fetchBrief(points, ctrl.signal)
      .then((list) => setBrief(Object.fromEntries(list.map((b) => [`${b.lat.toFixed(3)},${b.lon.toFixed(3)}`, b]))))
      .catch(() => { /* the cards simply show no temperature */ })
    return () => ctrl.abort()
  }, [points])

  if (!saved.length) return null
  return (
    <section aria-label={t("saved.title")} className="scroll-row mt-2 flex gap-2 overflow-x-auto pb-1">
      {saved.map((place) => {
        const active = !!current && samePlace(place, current)
        const now = brief[`${place.lat.toFixed(3)},${place.lon.toFixed(3)}`]
        return (
          <div key={`${place.name}-${place.lat}`}
            className={cn("group relative flex w-[8.5rem] shrink-0 items-center gap-2 rounded-2xl border px-3 py-2 shadow-[0_8px_24px_-12px_rgb(0_0_0/0.8)] transition-colors",
              active ? "border-sky-300 bg-sky-700/95 ring-1 ring-sky-300/60" : "border-white/15 bg-slate-950/80 hover:bg-slate-950/90")}>
            <button type="button" onClick={() => onSelect(place)} aria-current={active || undefined}
              className="flex min-w-0 flex-1 items-center gap-2 rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-sky-300">
              <span className="min-w-0 flex-1">
                <span className="block truncate pr-4 text-[13px] font-medium text-white/90" translate="no">{place.name}</span>
                <span className="block text-lg font-semibold tabular-nums text-white">
                  {now?.temperature != null ? fmt.temp(now.temperature, units) : "…"}
                </span>
              </span>
              {now?.condition && <WeatherIcon condition={now.condition} isDay={now.is_day} className="size-7 shrink-0" />}
            </button>
            <button type="button" onClick={() => removeSaved(place)} aria-label={t("saved.remove", { name: place.name })}
              className="absolute right-1 top-1 rounded-lg p-1 text-white/45 outline-none transition-colors hover:bg-white/15 hover:text-white focus-visible:ring-2 focus-visible:ring-sky-300 focus-visible:text-white">
              <X aria-hidden="true" className="size-3.5" />
            </button>
          </div>
        )
      })}
    </section>
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
  const { t } = useT()
  const rotate = deg == null ? 0 : (deg + 180) % 360
  return (
    <svg viewBox="0 0 120 120" className="size-28 shrink-0 sm:size-32" role="img" aria-label={deg == null ? t("wind.unknown") : t("wind.from", { dir: compass(deg) })}>
      <circle cx="60" cy="60" r="56" fill="none" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" />
      <circle cx="60" cy="60" r="44" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="1" />
      {Array.from({ length: 36 }, (_, i) => (
        <line key={i} x1="60" y1="7" x2="60" y2={i % 9 === 0 ? 15 : 11} stroke="rgba(255,255,255,0.4)" strokeWidth="1"
          transform={`rotate(${i * 10} 60 60)`} />
      ))}
      {[[t("dir.N"), 60, 26], [t("dir.E"), 95, 64], [t("dir.S"), 60, 100], [t("dir.W"), 25, 64]].map(([l, x, y]) => (
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
      <span className="sr-only">{translate(getLanguage(), "loading.weather")}</span>
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
  const key = m == null ? "vis.none"
    : m >= 10000 ? (lowest ? "vis.dayClear" : "vis.clear")
    : m >= 4000 ? (lowest ? "vis.dayHazy" : "vis.hazy")
    : (lowest ? "vis.dayPoor" : "vis.poor")
  return translate(getLanguage(), key)
}

function dayName(date: string, index: number, tz: string) {
  if (index === 0) return translate(getLanguage(), "day.today")
  if (index === 1) return translate(getLanguage(), "day.tomorrow")
  return new Intl.DateTimeFormat(localeOf(getLanguage()), { weekday: "long", timeZone: tz }).format(new Date(`${date}T12:00:00Z`))
}

function buildView(data: Data, sel: Selection, units: Units): View {
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) => translate(getLanguage(), key, values)
  const tz = data.location.timezone
  const now = data.now
  const humidity = (h: number | null | undefined, dew: number | null | undefined, when: "hum.now" | "hum.hour" | "hum.day") => ({
    value: h == null ? "–" : `${Math.round(h)}%`,
    note: dew == null ? undefined : t(when, { dew: fmt.temp(dew, units) }),
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
      summary: h.wind_speed != null
        ? t("hour.summary", { time: fmt.time(h.time, tz), description: h.description || title(h).toLowerCase(),
            temp: fmt.temp(h.temperature, units), wind: w.value, unit: w.unit, dir: compass(h.wind_direction) })
        : t("hour.summaryNoWind", { time: fmt.time(h.time, tz), description: h.description || title(h).toLowerCase(),
            temp: fmt.temp(h.temperature, units) }),
      feels: { value: fmt.temp(h.feels_like, units), note: feelsNote(h) },
      precip: {
        value: `${fmt.rain(h.precipitation_rate, units)}/h`,
        note: t((h.precipitation_rate ?? 0) > 0 ? "precip.hour" : "precip.hourNone"),
      },
      visibility: { value: fmt.distance(h.visibility, units), note: visibilityNote(h.visibility) },
      humidity: humidity(h.humidity, h.dew_point, "hum.hour"),
      uv: { value: h.uv_index, note: t((h.uv_index ?? 0) >= 3 ? "uvnote.hour" : "uvnote.hourNone") },
      wind: { speed: h.wind_speed, gust: h.wind_gust, direction: h.wind_direction, label: "wind" },
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
      feels: { value: fmt.temp(d.feels_like_max, units), note: t("feels.dayMax") },
      precip: {
        value: fmt.rain(d.precipitation, units),
        note: t((d.precipitation ?? 0) >= 1 ? "precip.dayUmbrella" : "precip.day"),
      },
      visibility: { value: fmt.distance(d.visibility_min, units), note: visibilityNote(d.visibility_min, true) },
      humidity: humidity(d.humidity, d.dew_point, "hum.day"),
      uv: {
        value: d.uv_max ?? null,
        note: (d.uv_max ?? 0) >= 3
          ? t("uvnote.dayPeak", { value: fmt.number(d.uv_max ?? 0), level: uvCategory(d.uv_max ?? null) })
          : t("uvnote.dayNone"),
      },
      wind: { speed: d.wind_max ?? null, gust: d.gust_max ?? null, direction: d.wind_direction ?? null, label: "windMax" },
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
      note: t("precip.next24", { rain: fmt.rain(data.precipitation.next_24h_mm, units) }),
    },
    visibility: { value: fmt.distance(now.visibility, units), note: visibilityNote(now.visibility) },
    humidity: humidity(now.humidity, now.dew_point, "hum.now"),
    uv: {
      value: now.uv_index,
      note: data.uv.protect_until
        ? t("uvnote.until", { time: fmt.time(data.uv.protect_until, tz) })
        : (data.uv.max_today ?? 0) >= 3
          ? t("uvnote.peak", { value: fmt.number(data.uv.max_today ?? 0), level: uvCategory(data.uv.max_today) })
          : t("uvnote.none"),
    },
    wind: { speed: now.wind_speed, gust: now.wind_gust, direction: now.wind_direction, label: "wind" },
  }
}

// Light glass: mostly see-through so the live sky stays visible; a soft text shadow keeps text readable.
const card = "rounded-3xl border border-white/15 bg-slate-950/30 [text-shadow:0_1px_2px_rgb(0_0_0/0.35)] shadow-[0_12px_40px_-18px_rgba(0,0,0,0.7)]"
const choice = "flex w-[4.75rem] flex-col items-center rounded-2xl px-2 py-3 outline-none transition-colors sm:w-[5.25rem] focus-visible:ring-2 focus-visible:ring-sky-300"

/** Cloud cover for the background scene; daily summaries only carry a description. */
function sceneFor(data: Data, sel: Selection): SkyScene {
  if (sel.kind === "hour") {
    const h = data.hourly[sel.index]
    return { condition: h.condition, isDay: h.is_day, cloudCover: h.cloud_cover }
  }
  if (sel.kind === "day") {
    const d = data.daily[sel.index]
    const desc = d.description.toLowerCase()
    return { condition: d.condition, isDay: true, cloudCover: desc.includes("few") || desc.includes("scattered") ? 40 : desc.includes("broken") ? 65 : 90 }
  }
  return { condition: data.now.condition, isDay: data.now.is_day, cloudCover: data.now.cloud_cover }
}

/** Temperature curve with rain bars for the hours ahead. */
function HourlyChart({ hours, units, tz }: { hours: Hour[]; units: Units; tz: string }) {
  const { t: tr } = useT()
  const id = useId()
  const temps = hours.map((h) => (h.temperature == null ? null : fmt.tempValue(h.temperature, units)))
  const known = temps.filter((t): t is number => t != null)
  if (known.length < 3) return null
  const min = Math.min(...known), max = Math.max(...known)
  const span = Math.max(max - min, 4)
  const W = 720, H = 150, padX = 26, padTop = 26, padBottom = 34
  const x = (i: number) => padX + (i * (W - padX * 2)) / Math.max(hours.length - 1, 1)
  const y = (t: number) => padTop + (1 - (t - min) / span) * (H - padTop - padBottom)
  const points = temps.map((t, i) => (t == null ? null : [x(i), y(t)] as const)).filter(Boolean) as (readonly [number, number])[]
  const line = points.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ")
  const area = `${line} L${points[points.length - 1][0].toFixed(1)},${H - padBottom} L${points[0][0].toFixed(1)},${H - padBottom} Z`
  const rain = hours.map((h) => Math.min((h.precipitation_rate ?? 0) / 2, 1))  // 2 mm/h fills the bar

  return (
    <figure className="mt-3">
      <figcaption className="sr-only">{tr("chart.label")}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-36 w-full" role="img"
        aria-label={tr("chart.label")}>
        <defs>
          <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#7cc7ff" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#7cc7ff" stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* rain first, so the temperature line stays on top */}
        {rain.map((r, i) => r > 0.02 && (
          <rect key={i} x={x(i) - 7} width="14" y={H - padBottom - r * 46} height={r * 46} rx="3" fill="#38bdf8" opacity="0.55" />
        ))}
        <path d={area} fill={`url(#${id}-fill)`} />
        <path d={line} fill="none" stroke="#bfe3ff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        {temps.map((t, i) => t == null ? null : (
          <g key={i}>
            <circle cx={x(i)} cy={y(t)} r={i === 0 ? 4.5 : 2.5} fill={i === 0 ? "#fff" : "#bfe3ff"} />
            {(i === 0 || i % 2 === 0) && (
              <>
                <text x={x(i)} y={y(t) - 10} textAnchor="middle" fontSize="15" fontWeight="500" fill="#fff">{t}°</text>
                <text x={x(i)} y={H - 10} textAnchor="middle" fontSize="12" fill="rgba(255,255,255,0.55)">
                  {i === 0 ? tr("now.badge") : fmt.hour(hours[i].time, tz)}
                </text>
              </>
            )}
          </g>
        ))}
      </svg>
    </figure>
  )
}

/** Sunrise, sunset and where the day currently stands. */
function SunCard({ sun, tz, className }: { sun: Data["sun"]; tz: string; className?: string }) {
  const { t } = useT()
  const id = useId()
  if (!sun.sunrise || !sun.sunset) return null
  const rise = new Date(sun.sunrise).getTime(), set = new Date(sun.sunset).getTime(), now = Date.now()
  const share = Math.min(Math.max((now - rise) / (set - rise), 0), 1)
  const daylight = set - rise
  const hours = Math.floor(daylight / 3600_000), mins = Math.round((daylight % 3600_000) / 60_000)
  const W = 260, H = 96, r = 96
  const angle = Math.PI * (1 - share)
  const cx = W / 2 + Math.cos(angle) * r, cy = H - 6 - Math.sin(angle) * r
  const up = now >= rise && now <= set

  return (
    <section aria-labelledby="sun-title" className={cn(card, "min-w-0 p-4 sm:p-5", className)}>
      <CardTitle id="sun-title" icon={<Sunrise />}>{t("card.sun")}</CardTitle>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 h-24 w-full" aria-hidden="true">
        <defs>
          <linearGradient id={`${id}-arc`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#fbbf24" stopOpacity="0.25" />
            <stop offset="50%" stopColor="#fde68a" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#fbbf24" stopOpacity="0.25" />
          </linearGradient>
        </defs>
        <path d={`M${W / 2 - r},${H - 6} A${r},${r} 0 0 1 ${W / 2 + r},${H - 6}`} fill="none"
          stroke={`url(#${id}-arc)`} strokeWidth="2" strokeDasharray="4 5" />
        <line x1="6" y1={H - 6} x2={W - 6} y2={H - 6} stroke="rgba(255,255,255,0.15)" strokeWidth="1" />
        {up && <circle cx={cx} cy={cy} r="7" fill="#fde68a" stroke="#fff7d6" strokeWidth="2" />}
      </svg>
      <dl className="mt-1 flex items-end justify-between gap-2 text-sm">
        <div><dt className="text-white/55">{t("sun.sunrise")}</dt><dd className="text-lg font-medium tabular-nums text-white">{fmt.time(sun.sunrise, tz)}</dd></div>
        <div className="text-center"><dt className="text-white/55">{t("sun.daylight")}</dt><dd className="tabular-nums text-white/85">{t("time.hoursMinutes", { h: hours, m: mins })}</dd></div>
        <div className="text-right"><dt className="text-white/55">{t("sun.sunset")}</dt><dd className="text-lg font-medium tabular-nums text-white">{fmt.time(sun.sunset, tz)}</dd></div>
      </dl>
    </section>
  )
}

/** Where the numbers come from, and how the forecast compares with the real reading. */
function TrustPanel({ data, units }: { data: Data; units: Units }) {
  const { t } = useT()
  const m = data.measured
  const model = m?.model_temperature, station = m?.station_temperature
  const gap = model != null && station != null ? Math.abs(model - station) : null
  const run = data.meta.run ? new Date(data.meta.run) : null
  const rows: [string, ReactNode, string][] = [
    m
      ? [t("trust.measuredAt"), <><span translate="no">{m.station}</span>, {fmt.number(m.distance_km, 1)}&nbsp;km away</>,
         t("trust.reading", { age: fmt.age(m.age_minutes) })]
      : [t("trust.measuredAt"), t("trust.noStation"), t("trust.showingModel")],
    [t("trust.model"), (data.meta.model ?? "GFS").toUpperCase(),
     run ? t("trust.run", { time: run.toISOString().slice(11, 16), age: fmt.number(data.meta.data_age_hours ?? 0, 1) })
         : t("trust.runLatest")],
    gap != null
      ? [t("trust.compare"), <>{fmt.temp(model, units)} — {fmt.temp(station, units)}</>,
         t(gap < 1 ? "trust.gapSmall" : "trust.gapBig", { gap: fmt.number(gap, 1) })]
      : [t("trust.what"), t("trust.stationReading"), t("trust.forecastOnly")],
  ]
  return (
    <section aria-labelledby="trust-title" className={cn(card, "order-4 p-4 sm:p-5 lg:col-span-2")}>
      <CardTitle id="trust-title" icon={<ShieldCheck />}>{t("card.trust")}</CardTitle>
      <dl className="mt-3 grid gap-4 sm:grid-cols-3">
        {rows.map(([label, value, note]) => (
          <div key={label} className="min-w-0">
            <dt className="text-xs uppercase tracking-wide text-white/45">{label}</dt>
            <dd className="mt-1 text-[15px] font-medium text-white">{value}</dd>
            <dd className="text-[13px] leading-snug text-white/55">{note}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 border-t border-white/10 pt-3 text-[13px] text-white/50">
        {t("trust.sources")} <a className="text-sky-300 underline-offset-4 hover:underline" href="/#measured">{t("trust.how")}</a>
      </p>
    </section>
  )
}

export function WeatherDashboard({ data, units, search, onScene }: {
  data: Data
  units: Units
  search: ReactNode
  /** Called with the weather to show in the background: now, or the selected hour/day. */
  onScene?: (scene: SkyScene) => void
}) {
  const { t } = useT()
  const tz = data.location.timezone
  const [sel, setSel] = useState<Selection>({ kind: "now" })
  const [tab, setTab] = useState<"hourly" | "daily">("hourly")
  const heroRef = useRef<HTMLElement>(null)
  const hourly = data.hourly.filter((h) => new Date(h.time).getTime() >= Date.now() - 90 * 60 * 1000)
  const firstHour = data.hourly.length - hourly.length
  const view = buildView(data, sel, units)
  const wind = fmt.speed(view.wind.speed, units)
  const gust = fmt.speed(view.wind.gust, units)
  const here: Saved = { name: data.location.name, country: data.location.country, lat: data.location.lat, lon: data.location.lon }
  const saved = isSaved(useSavedPlaces(), here)
  const viewKey = sel.kind === "now" ? "now" : `${sel.kind}-${sel.index}`

  useEffect(() => {
    onScene?.(sceneFor(data, sel))
    // viewKey captures the selection; data changes only with a new place
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, data, onScene])

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
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="flex min-w-0 flex-wrap items-center gap-1.5 text-sm text-white/80">
              <MapPin aria-hidden="true" className="size-4 shrink-0" />
              <span className="min-w-0 text-pretty" translate="no">{data.location.name}{data.location.country ? `, ${data.location.country}` : ""}</span>
              {data.location.detail && (
                <span className="basis-full pl-5 text-xs text-white/50" translate="no">{data.location.detail}</span>
              )}
              <button type="button" onClick={() => toggleSaved(here)} aria-pressed={saved}
                title={t(saved ? "saved.added" : "saved.add")} aria-label={t(saved ? "saved.added" : "saved.add")}
                className={cn("-my-1 shrink-0 rounded-full p-1.5 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-300",
                  saved ? "text-amber-300 hover:text-amber-200" : "text-white/50 hover:text-white")}>
                <Star aria-hidden="true" className={cn("size-4", saved && "fill-amber-300")} />
              </button>
              {data.location.name_source === "osm" && (
                <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer"
                  className="shrink-0 text-[11px] text-white/45 underline-offset-2 hover:text-white/70 hover:underline">© OpenStreetMap contributors</a>
              )}
            </p>
            {sel.kind !== "now" ? (
              <button type="button" onClick={() => setSel({ kind: "now" })}
                className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-xs font-medium text-white outline-none transition-colors hover:bg-white/20 focus-visible:ring-2 focus-visible:ring-sky-300">
                <RotateCcw aria-hidden="true" className="size-3.5" />
                {t("now.back")}
              </button>
            ) : data.meta.from_store ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-400/15 px-2.5 py-1 text-xs font-medium text-amber-100">
                <RotateCcw aria-hidden="true" className="size-3.5" />
                {t("now.updating", { age: fmt.age(data.meta.stored_age_minutes ?? 0) })}
              </span>
            ) : data.measured ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-400/15 px-2.5 py-1 text-xs font-medium text-emerald-200">
                <Radio aria-hidden="true" className="size-3.5" />
                {t("now.measured", { age: fmt.age(data.measured.age_minutes) })}
              </span>
            ) : (
              <span className="rounded-full bg-sky-400/15 px-2.5 py-1 text-xs font-medium text-sky-200">{t("now.model")}</span>
            )}
          </div>

          <div key={viewKey} className="mt-6 flex flex-col items-center text-center animate-in fade-in slide-in-from-bottom-1 duration-300 sm:mt-8">
            <p className={cn("mb-3 rounded-full px-3 py-1 text-xs font-medium tracking-wide",
              view.heading ? "bg-sky-400/15 text-sky-100" : "invisible")}>
              {view.heading ? <>{view.forecast ? t("now.forecast") : ""}{view.heading}</> : t("now.badge")}
            </p>
            <WeatherIcon condition={view.condition} isDay={view.isDay} className="size-14 sm:size-16" />
            <p className="mt-2 text-[5.5rem] leading-none font-light tracking-tight text-white tabular-nums sm:text-[7rem]">
              {view.temp == null ? "–" : view.temp}
              <span aria-hidden="true">°</span>
              <span className="sr-only">{t(units === "imperial" ? "unit.fahrenheit" : "unit.celsius")}</span>
            </p>
            {view.range && <p className="mt-1 text-sm tabular-nums text-white/70">{view.range}</p>}
            <h2 id="now-title" className="mt-2 text-balance text-3xl font-medium text-white sm:text-4xl">{view.title}</h2>
            <p className="mt-4 max-w-md text-pretty text-sm leading-relaxed text-white/80 sm:text-[15px]">{view.summary}</p>
            {sel.kind === "now" && data.measured && (
              <p className="mt-3 text-xs text-white/55">
                {t("now.station", { station: data.measured.station, km: fmt.number(data.measured.distance_km, 1) })}
              </p>
            )}
          </div>

          {sel.kind === "now" && data.alerts.length > 0 && (
            <ul className="mt-6 space-y-2" aria-label={t("aria.warnings")}>
              {data.alerts.map((a) => (
                <li key={a.event + a.start}
                  className={cn("flex items-center gap-2 rounded-xl px-3 py-2 text-sm",
                    a.severity === "severe" ? "bg-red-500/20 text-red-100" : "bg-amber-400/15 text-amber-100")}>
                  <AlertTriangle aria-hidden="true" className="size-4 shrink-0" />
                  <span className="min-w-0"><strong className="font-medium">{alertName(a.event)}</strong> · {a.start === a.end ? t("alert.around", { time: fmt.time(a.start, tz) }) : <>{fmt.time(a.start, tz)}–{fmt.time(a.end, tz)}</>}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* Detail tiles in one row across the dashboard (2×2 on phones, right under the summary) */}
      <div className="order-2 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:order-3 lg:col-span-2">
        <Tile icon={<Thermometer />} label={t("tile.feels")} value={view.feels.value} note={view.feels.note} />
        <Tile icon={<Droplet />} label={t("tile.precip")} value={view.precip.value} note={view.precip.note} />
        <Tile icon={<Eye />} label={t("tile.visibility")} value={view.visibility.value} note={view.visibility.note} />
        <Tile icon={<Droplets />} label={t("tile.humidity")} value={view.humidity.value} note={view.humidity.note} />
      </div>

      <TrustPanel data={data} units={units} />

      {/* Right column: hourly or 10-day (toggle), UV, wind. Choosing an hour or a day updates the summary. */}
      <div className="order-3 flex min-w-0 flex-col gap-4 lg:order-2">
        <section aria-label="Forecast" className={cn(card, "p-4 sm:p-5")}>
          <div className="flex items-center justify-between gap-3">
            <CardTitle id="forecast-title" icon={tab === "hourly" ? <Clock /> : <CalendarDays />}>
              {tab === "hourly" ? t("card.hourly") : t("card.daily", { n: data.daily.length })}
            </CardTitle>
            <div role="tablist" aria-label={t("aria.range")} className="flex shrink-0 rounded-full bg-white/10 p-1">
              {([["hourly", t("tab.hourly")], ["daily", t("tab.days", { n: data.daily.length })]] as const).map(([key, label]) => (
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
            {tab === "hourly" && <HourlyChart hours={hourly} units={units} tz={tz} />}
            <ol key={tab} role="list" aria-label={t(tab === "hourly" ? "aria.hourlyList" : "aria.dailyList")}
              className="scroll-row mt-3 flex snap-x snap-mandatory gap-2 overflow-x-auto p-0.5 pb-2 animate-in fade-in duration-300">
              {tab === "hourly" ? hourly.map((h, i) => {
                const selected = i === 0 ? sel.kind === "now" : sel.kind === "hour" && sel.index === firstHour + i
                return (
                  <li key={h.time} className="shrink-0 snap-start">
                    <button type="button" aria-pressed={selected}
                      onClick={() => select(i === 0 ? { kind: "now" } : { kind: "hour", index: firstHour + i })}
                      className={cn(choice, "gap-2", selected ? "bg-white/20 ring-1 ring-white/25" : "hover:bg-white/10")}>
                      <span className="whitespace-nowrap text-sm text-white/75">{i === 0 ? t("now.badge") : fmt.hour(h.time, tz)}</span>
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
                      <span className="whitespace-nowrap text-sm text-white/80">{i === 0 ? t("day.today") : fmt.weekday(d.date, tz)}</span>
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
          <SunCard sun={data.sun} tz={tz} className="sm:col-span-2" />
          <section aria-labelledby="uv-title" className={cn(card, "flex min-w-0 flex-col p-4 sm:p-5")}>
            <CardTitle id="uv-title" icon={<Sun />}>{sel.kind === "day" ? t("card.uvPeak") : t("card.uv")}</CardTitle>
            <p className="mt-4 text-4xl font-medium tabular-nums text-white">{view.uv.value == null ? "–" : fmt.number(view.uv.value, 0)}</p>
            <p className="text-lg text-white/90">{uvCategory(view.uv.value)}</p>
            <UvBar value={view.uv.value} />
            <p className="mt-auto pt-4 text-[13px] text-white/65">{view.uv.note}</p>
          </section>

          <section aria-labelledby="wind-title" className={cn(card, "min-w-0 p-4 sm:p-5")}>
            <CardTitle id="wind-title" icon={<Wind />}>{view.wind.label === "windMax" ? t("card.windMax") : t("card.wind")}</CardTitle>
            <div className="mt-3 flex items-center justify-between gap-3">
              <dl className="min-w-0 flex-1 divide-y divide-white/10">
                <div className="flex items-baseline gap-2 pb-3">
                  <dt className="order-2 text-sm leading-tight text-white/70"><span className="block uppercase">{wind.unit}</span>{t("card.wind")}</dt>
                  <dd className="order-1 text-4xl font-medium tabular-nums text-white">{wind.value}</dd>
                </div>
                <div className="flex items-baseline gap-2 pt-3">
                  <dt className="order-2 text-sm leading-tight text-white/70"><span className="block uppercase">{gust.unit}</span>{t("card.gusts")}</dt>
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
