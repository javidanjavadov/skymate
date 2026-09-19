import { useId, type ReactNode } from "react"
import {
  AlertTriangle, CalendarDays, Clock, Droplet, Droplets, Eye, LocateFixed, MapPin, Radio, Search, Sun, Thermometer, Wind,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { MagicCard } from "@/components/ui/magic-card"
import { Skeleton } from "@/components/ui/skeleton"
import { WeatherIcon } from "@/components/weather/weather-icon"
import { cn } from "@/lib/utils"
import {
  compass, feelsNote, fmt, summary, title, uvCategory, type Dashboard as Data, type Units,
} from "@/lib/weather"

const panel = "rounded-[2rem] border border-white/15 bg-slate-950/25 backdrop-blur-md shadow-[0_20px_60px_-20px_rgba(0,0,0,0.6)]"

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
    <MagicCard
      className="min-w-0 rounded-2xl"
      gradientColor="rgba(125, 190, 255, 0.10)"
      gradientFrom="#7cc7ff"
      gradientTo="#a78bfa"
      gradientSize={180}
    >
      <div className="flex h-full min-h-32 flex-col gap-1 rounded-2xl bg-slate-950/50 p-4 sm:min-h-36">
        <CardTitle icon={icon}>{label}</CardTitle>
        <div className="mt-1 text-3xl font-medium tabular-nums text-white sm:text-4xl">{value}</div>
        {note && <p className="mt-auto text-pretty text-[13px] leading-snug text-white/65">{note}</p>}
      </div>
    </MagicCard>
  )
}

export function SearchBar({ onSearch, onLocate, busy, defaultValue }: {
  onSearch: (q: string) => void
  onLocate: () => void
  busy: boolean
  defaultValue: string
}) {
  const id = useId()
  return (
    <form
      role="search"
      className="flex items-center gap-2 rounded-full border border-white/10 bg-white/10 p-1.5 pl-4 backdrop-blur-md focus-within:ring-2 focus-within:ring-sky-300/60"
      onSubmit={(e) => {
        e.preventDefault()
        const q = String(new FormData(e.currentTarget).get("q") ?? "").trim()
        if (q) onSearch(q.slice(0, 100))
      }}
    >
      <MapPin aria-hidden="true" className="size-4 shrink-0 text-white/70" />
      <label htmlFor={id} className="sr-only">City</label>
      <Input
        id={id}
        name="q"
        key={defaultValue}
        defaultValue={defaultValue}
        maxLength={100}
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
      <Button type="submit" disabled={busy} className="h-9 shrink-0 rounded-full bg-white px-4 text-slate-900 hover:bg-sky-100">
        <Search aria-hidden="true" className="sm:hidden" />
        <span className="max-sm:sr-only">{busy ? "Searching…" : "Search"}</span>
      </Button>
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
        <g style={{ transformBox: "fill-box" }} transform={`rotate(${rotate} 60 60)`}>
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
    <div className={cn(panel, "grid gap-4 p-3 sm:p-4 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] lg:p-5")} aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading weather…</span>
      <div className="space-y-4">
        <Skeleton className="h-[26rem] rounded-3xl bg-white/10" />
        <div className="grid grid-cols-2 gap-3"><Skeleton className="h-32 rounded-2xl bg-white/10" /><Skeleton className="h-32 rounded-2xl bg-white/10" /></div>
      </div>
      <div className="space-y-4">
        <Skeleton className="h-44 rounded-3xl bg-white/10" /><Skeleton className="h-44 rounded-3xl bg-white/10" />
        <div className="grid gap-4 sm:grid-cols-2"><Skeleton className="h-40 rounded-3xl bg-white/10" /><Skeleton className="h-40 rounded-3xl bg-white/10" /></div>
      </div>
    </div>
  )
}

export function WeatherDashboard({ data, units, search }: { data: Data; units: Units; search: ReactNode }) {
  const tz = data.location.timezone
  const now = data.now
  const temp = now.temperature == null ? null : fmt.tempValue(now.temperature, units)
  const wind = fmt.speed(now.wind_speed, units)
  const gust = fmt.speed(now.wind_gust, units)
  const hourly = data.hourly.filter((h) => new Date(h.time).getTime() >= Date.now() - 90 * 60 * 1000)

  return (
    <div className={cn(panel, "grid gap-4 p-3 sm:p-4 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] lg:p-5")}>
      {/* Left column: search, now, detail tiles */}
      <div className="flex min-w-0 flex-col gap-4">
        {search}
        <section aria-labelledby="now-title" className="relative overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-b from-white/[0.08] to-white/[0.02] p-5 sm:p-7">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="flex min-w-0 items-center gap-1.5 text-sm text-white/80">
                <MapPin aria-hidden="true" className="size-4 shrink-0" />
                <span className="truncate" translate="no">{data.location.name}{data.location.country ? `, ${data.location.country}` : ""}</span>
              </p>
              {data.measured ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-400/15 px-2.5 py-1 text-xs font-medium text-emerald-200">
                  <Radio aria-hidden="true" className="size-3.5" />
                  Measured {fmt.age(data.measured.age_minutes)}
                </span>
              ) : (
                <span className="rounded-full bg-sky-400/15 px-2.5 py-1 text-xs font-medium text-sky-200">Model estimate</span>
              )}
            </div>

            <div className="mt-6 flex flex-col items-center text-center sm:mt-10">
              <WeatherIcon condition={now.condition} isDay={now.is_day} className="size-14 sm:size-16" />
              <p className="mt-2 text-[5.5rem] leading-none font-light tracking-tight text-white tabular-nums sm:text-[7rem]">
                {temp == null ? "–" : temp}
                <span aria-hidden="true">°</span>
                <span className="sr-only">{units === "imperial" ? "degrees Fahrenheit" : "degrees Celsius"}</span>
              </p>
              <h2 id="now-title" className="mt-2 text-balance text-3xl font-medium text-white sm:text-4xl">{title(now)}</h2>
              <p className="mt-4 max-w-md text-pretty text-sm leading-relaxed text-white/80 sm:text-[15px]">{summary(data, units)}</p>
              {data.measured && (
                <p className="mt-3 text-xs text-white/55">
                  Temperature measured at <span translate="no">{data.measured.station}</span>, {fmt.number(data.measured.distance_km, 1)}&nbsp;km away
                </p>
              )}
            </div>

            {data.alerts.length > 0 && (
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

        <div className="grid grid-cols-2 gap-3">
          <Tile icon={<Thermometer />} label="Feels like" value={fmt.temp(now.feels_like, units)} note={feelsNote(data)} />
          <Tile icon={<Droplet />} label="Precipitation" value={fmt.rain(data.precipitation.today_mm, units)}
            note={<>Today · {fmt.rain(data.precipitation.next_24h_mm, units)} expected in the next 24&nbsp;h</>} />
          <Tile icon={<Eye />} label="Visibility" value={fmt.distance(now.visibility, units)}
            note={now.visibility == null ? "No visibility reading nearby." : now.visibility >= 10000 ? "Perfectly clear view." : now.visibility >= 4000 ? "Slightly hazy." : "Reduced visibility, take care."} />
          <Tile icon={<Droplets />} label="Humidity" value={now.humidity == null ? "–" : `${Math.round(now.humidity)}%`}
            note={now.dew_point == null ? undefined : <>The dew point is {fmt.temp(now.dew_point, units)} right now.</>} />
        </div>
      </div>

      {/* Right column: hourly, 10-day, UV, wind */}
      <div className="flex min-w-0 flex-col gap-4">
        <section aria-labelledby="hourly-title" className="rounded-3xl border border-white/10 bg-slate-950/40 p-4 sm:p-5">
          <CardTitle id="hourly-title" icon={<Clock />}>Hourly Forecast</CardTitle>
          <div className="mt-3 border-t border-white/10" />
          <ol role="list" tabIndex={0} aria-label="Hourly forecast, scroll horizontally"
            className="scroll-row mt-3 flex snap-x snap-mandatory gap-2 overflow-x-auto pb-2 outline-none focus-visible:ring-2 focus-visible:ring-sky-300/60">
            {hourly.map((h, i) => (
              <li key={h.time}
                className={cn("flex w-[4.75rem] shrink-0 snap-start flex-col items-center gap-2 rounded-2xl px-2 py-3 sm:w-[5.25rem]",
                  i === 0 ? "bg-white/15 ring-1 ring-white/15" : "hover:bg-white/5")}>
                <span className="whitespace-nowrap text-sm text-white/75">{i === 0 ? "Now" : fmt.hour(h.time, tz)}</span>
                <span className="text-2xl font-medium tabular-nums text-white">{fmt.temp(h.temperature, units)}</span>
                <WeatherIcon condition={h.condition} isDay={h.is_day} className="size-6" />
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="daily-title" className="rounded-3xl border border-white/10 bg-slate-950/40 p-4 sm:p-5">
          <CardTitle id="daily-title" icon={<CalendarDays />}>{data.daily.length}-Day Forecast</CardTitle>
          <div className="mt-3 border-t border-white/10" />
          <ol role="list" tabIndex={0} aria-label="Daily forecast, scroll horizontally"
            className="scroll-row mt-3 flex snap-x snap-mandatory gap-2 overflow-x-auto pb-2 outline-none focus-visible:ring-2 focus-visible:ring-sky-300/60">
            {data.daily.map((d, i) => (
              <li key={d.date}
                className={cn("flex w-[4.75rem] shrink-0 snap-start flex-col items-center gap-1 rounded-2xl px-2 py-3 sm:w-[5.25rem]",
                  i === 0 ? "bg-white/15 ring-1 ring-white/15" : "hover:bg-white/5")}>
                <span className="whitespace-nowrap text-sm text-white/80">{i === 0 ? "Today" : fmt.weekday(d.date, tz)}</span>
                <span className="text-xs text-white/50 tabular-nums">{fmt.dayMonth(d.date, tz)}</span>
                <span className="mt-1 text-2xl font-medium tabular-nums text-white">{fmt.temp(d.max, units)}</span>
                <span className="text-xs tabular-nums text-white/55">{fmt.temp(d.min, units)}</span>
                <WeatherIcon condition={d.condition} className="mt-1 size-6" />
              </li>
            ))}
          </ol>
        </section>

        <div className="grid gap-4 sm:grid-cols-2">
          <section aria-labelledby="uv-title" className="flex min-w-0 flex-col rounded-3xl border border-white/10 bg-slate-950/40 p-4 sm:p-5">
            <CardTitle id="uv-title" icon={<Sun />}>UV Index</CardTitle>
            <p className="mt-4 text-4xl font-medium tabular-nums text-white">{now.uv_index == null ? "–" : fmt.number(now.uv_index, 0)}</p>
            <p className="text-lg text-white/90">{uvCategory(now.uv_index)}</p>
            <UvBar value={now.uv_index} />
            <p className="mt-auto pt-4 text-[13px] text-white/65">
              {data.uv.protect_until
                ? <>Use sun protection until {fmt.time(data.uv.protect_until, tz)}.</>
                : (data.uv.max_today ?? 0) >= 3
                  ? <>Today’s peak: {fmt.number(data.uv.max_today ?? 0)} ({uvCategory(data.uv.max_today)}). Use sun protection around midday.</>
                  : "No sun protection needed today."}
            </p>
          </section>

          <section aria-labelledby="wind-title" className="min-w-0 rounded-3xl border border-white/10 bg-slate-950/40 p-4 sm:p-5">
            <CardTitle id="wind-title" icon={<Wind />}>Wind</CardTitle>
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
              <Compass deg={now.wind_direction} />
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
