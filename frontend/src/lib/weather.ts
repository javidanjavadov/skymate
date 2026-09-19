export type Condition = "Clear" | "Clouds" | "Rain" | "Drizzle" | "Thunderstorm" | "Snow" | "Mist" | "Fog"

export interface Dashboard {
  location: { name: string; country: string; timezone: string; lat: number; lon: number }
  now: {
    temperature: number | null
    feels_like: number | null
    humidity: number | null
    dew_point: number | null
    pressure: number | null
    wind_speed: number | null
    wind_gust: number | null
    wind_direction: number | null
    visibility: number | null
    cloud_cover: number | null
    condition: Condition
    description: string
    is_day: boolean
    uv_index: number | null
  }
  measured: { station: string; distance_km: number; age_minutes: number; time: string } | null
  sun: { sunrise?: string | null; sunset?: string | null }
  precipitation: { today_mm: number; next_24h_mm: number }
  uv: { now: number | null; max_today: number | null; protect_until: string | null }
  hourly: { time: string; temperature: number | null; condition: Condition; is_day: boolean; precipitation_rate: number | null }[]
  daily: { date: string; min: number | null; max: number | null; condition: Condition; description: string; precipitation: number | null }[]
  alerts: { event: string; severity: "severe" | "moderate" | "minor"; start: string; end: string }[]
  meta: { source: string; data_age_hours: number | null }
}

export type Units = "metric" | "imperial"

export class WeatherError extends Error {}

export async function fetchDashboard(query: { q?: string; lat?: number; lon?: number }, signal?: AbortSignal) {
  const params = new URLSearchParams()
  if (query.q) params.set("q", query.q)
  if (query.lat !== undefined && query.lon !== undefined) {
    params.set("lat", query.lat.toFixed(4))
    params.set("lon", query.lon.toFixed(4))
  }
  let res: Response
  try {
    res = await fetch(`/site/api/weather?${params}`, { signal })
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e
    throw new WeatherError("Can’t reach SkyMate. Check your connection and try again.")
  }
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new WeatherError(body.error ?? "Something went wrong. Try again in a moment.")
  return body as Dashboard
}

const locale = typeof navigator !== "undefined" ? navigator.languages?.[0] ?? navigator.language : "en"

export const fmt = {
  temp(c: number | null | undefined, u: Units) {
    if (c == null) return "–"
    return `${Math.round(u === "imperial" ? c * 9 / 5 + 32 : c)}°`
  },
  tempValue(c: number, u: Units) {
    return Math.round(u === "imperial" ? c * 9 / 5 + 32 : c)
  },
  speed(ms: number | null | undefined, u: Units) {
    if (ms == null) return { value: "–", unit: u === "imperial" ? "mph" : "km/h" }
    const v = u === "imperial" ? ms * 2.23694 : ms * 3.6
    return { value: new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(v), unit: u === "imperial" ? "mph" : "km/h" }
  },
  distance(m: number | null | undefined, u: Units) {
    if (m == null) return "–"
    const v = u === "imperial" ? m / 1609.34 : m / 1000
    const unit = u === "imperial" ? "mi" : "km"
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: v < 10 ? 1 : 0 }).format(v)} ${unit}`
  },
  rain(mm: number | null | undefined, u: Units) {
    if (mm == null) return "–"
    const v = u === "imperial" ? mm / 25.4 : mm
    const unit = u === "imperial" ? "in" : "mm"
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: u === "imperial" ? 2 : 1 }).format(v)} ${unit}`
  },
  number(v: number, digits = 0) {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(v)
  },
  time(iso: string, timeZone: string) {
    return new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", timeZone }).format(new Date(iso))
  },
  hour(iso: string, timeZone: string) {
    return new Intl.DateTimeFormat(locale, { hour: "numeric", timeZone }).format(new Date(iso))
  },
  weekday(date: string, timeZone: string) {
    return new Intl.DateTimeFormat(locale, { weekday: "short", timeZone }).format(new Date(`${date}T12:00:00Z`))
  },
  dayMonth(date: string, timeZone: string) {
    return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "2-digit", timeZone }).format(new Date(`${date}T12:00:00Z`))
  },
  age(minutes: number) {
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" })
    return minutes < 90 ? rtf.format(-minutes, "minute") : rtf.format(-Math.round(minutes / 60), "hour")
  },
}

export const CONDITION_TITLE: Record<Condition, string> = {
  Clear: "Clear Sky",
  Clouds: "Cloudy",
  Rain: "Rainy Day",
  Drizzle: "Light Drizzle",
  Thunderstorm: "Thunderstorms",
  Snow: "Snowfall",
  Mist: "Misty",
  Fog: "Foggy",
}

export function title(now: Dashboard["now"]) {
  if (now.condition === "Clear" && !now.is_day) return "Clear Night"
  if (now.condition === "Clouds") {
    const d = now.description.toLowerCase()
    if (d.includes("few") || d.includes("scattered")) return "Partly Cloudy"
    if (d.includes("overcast")) return "Overcast"
  }
  return CONDITION_TITLE[now.condition] ?? "Weather"
}

export function summary(d: Dashboard, u: Units) {
  const today = d.daily[0]
  if (!today) return ""
  const max = fmt.temp(today.max, u)
  const rain = today.precipitation ?? 0
  switch (today.condition) {
    case "Thunderstorm":
      return `Today, expect thunderstorms with temperatures reaching a maximum of ${max}. Stay indoors during lightning and avoid open areas.`
    case "Rain":
      return `Today, expect a rainy day with temperatures reaching a maximum of ${max}. Grab your umbrella and raincoat before heading out.`
    case "Drizzle":
      return `Today, expect light drizzle and a maximum of ${max}. A light jacket and an umbrella will keep you comfortable.`
    case "Snow":
      return `Today, expect snow with a maximum of ${max}. Allow extra time for travel and dress in warm layers.`
    case "Fog":
    case "Mist":
      return `Today, expect reduced visibility and a maximum of ${max}. Take extra care on the roads.`
    case "Clear":
      return `Today, expect clear skies with temperatures reaching a maximum of ${max}.${(d.uv.max_today ?? 0) >= 6 ? " UV is high, so use sun protection." : " A great day to be outside."}`
    default:
      return `Today, expect ${today.description || "clouds"} with a maximum of ${max}.${rain >= 1 ? " Keep an umbrella handy." : ""}`
  }
}

export function feelsNote(d: Dashboard) {
  const { temperature: t, feels_like: f, humidity: h, wind_speed: w } = d.now
  if (t == null || f == null) return ""
  if (f - t >= 1.5) return (h ?? 0) >= 60 ? "Humidity is making it feel warmer." : "Sunshine is making it feel warmer."
  if (t - f >= 1.5) return (w ?? 0) >= 4 ? "Wind is making it feel colder." : "It feels slightly colder than it is."
  return "Similar to the actual temperature."
}

export function uvCategory(raw: number | null) {
  if (raw == null) return "Unknown"
  const v = Math.round(raw)
  if (v < 3) return "Low"
  if (v < 6) return "Moderate"
  if (v < 8) return "High"
  if (v < 11) return "Very High"
  return "Extreme"
}

export function compass(deg: number | null) {
  if (deg == null) return ""
  return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(deg / 45) % 8]
}
