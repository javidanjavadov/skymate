export type Condition = "Clear" | "Clouds" | "Rain" | "Drizzle" | "Thunderstorm" | "Snow" | "Mist" | "Fog"

export interface Dashboard {
  /** name_source "osm": neighbourhood name from OpenStreetMap (needs attribution) */
  location: { name: string; country: string; timezone: string; lat: number; lon: number; name_source?: "osm" | "skymate"; detail?: string }
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
  hourly: Hour[]
  daily: Day[]
  alerts: { event: string; severity: "severe" | "moderate" | "minor"; start: string; end: string }[]
  /** stale: forecast files are reloading after a restart, so this is the last good answer */
  meta: { source: string; data_age_hours: number | null; stale?: boolean; made_at?: string; stale_age_minutes?: number }
}

export interface Hour {
  time: string
  temperature: number | null
  feels_like: number | null
  condition: Condition
  description: string
  is_day: boolean
  precipitation_rate: number | null
  humidity: number | null
  dew_point: number | null
  visibility: number | null
  wind_speed: number | null
  wind_gust: number | null
  wind_direction: number | null
  uv_index: number | null
  cloud_cover: number | null
}

export interface Day {
  date: string
  min: number | null
  max: number | null
  condition: Condition
  description: string
  precipitation: number | null
  uv_max?: number | null
  wind_max?: number | null
  gust_max?: number | null
  feels_like_max?: number | null
  humidity?: number | null
  dew_point?: number | null
  visibility_min?: number | null
  wind_direction?: number | null
}

export type Units = "metric" | "imperial"

export class WeatherError extends Error {}

export async function fetchDashboard(query: { q?: string; lat?: number; lon?: number; gps?: boolean }, signal?: AbortSignal) {
  const params = new URLSearchParams()
  if (query.q) params.set("q", query.q)
  if (query.lat !== undefined && query.lon !== undefined) {
    params.set("lat", query.lat.toFixed(4))
    params.set("lon", query.lon.toFixed(4))
    if (query.gps) params.set("precise", "1")  // the visitor's own position: name the neighbourhood
  }
  let res: Response | undefined
  for (let attempt = 0; attempt < 2 && !res; attempt++) {
    const timeout = AbortSignal.timeout(20_000)
    try {
      res = await fetch(`/site/api/weather?${params}`, { signal: signal ? AbortSignal.any([signal, timeout]) : timeout })
    } catch (e) {
      if (signal?.aborted) throw e
      if (attempt === 1) {
        throw new WeatherError((e as Error).name === "TimeoutError"
          ? "SkyMate is taking too long to respond. It may be starting up; try again in a minute."
          : "Can’t reach SkyMate. Check your connection and try again.")
      }
    }
  }
  if (!res) throw new WeatherError("Can’t reach SkyMate. Check your connection and try again.")
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new WeatherError(body.error ?? "Something went wrong. Try again in a moment.")
  return body as Dashboard
}

export interface Place { name: string; country: string; lat: number; lon: number }

export async function searchPlaces(q: string, signal: AbortSignal): Promise<Place[]> {
  const res = await fetch(`/site/api/places?${new URLSearchParams({ q })}`, { signal })
  if (!res.ok) return []
  return ((await res.json()) as { places: Place[] }).places
}

/** OpenStreetMap's reverse lookup, called from the visitor's own browser (© OpenStreetMap contributors). */
const OSM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
const PLACE_CACHE = "skymate-places-v7"  // bumped when the name format changes, so old answers are dropped
// Only the neighbourhood comes from OpenStreetMap; the city name stays SkyMate's own, because OSM's city field
// varies by country ("Sabail Raion" for Baku, "Greater London" for London).
const PARTS = ["suburb", "quarter", "neighbourhood", "village", "hamlet", "city_district"] as const

function neighbourhood(address: Record<string, string>, city: string) {
  const skip = (v: string) => !v || /community board/i.test(v) || v.toLowerCase() === city.toLowerCase()
  return PARTS.map((k) => address[k]).find((v) => !skip(v)) ?? ""
}

function cachedPlaces(): Record<string, { name: string; country: string; detail: string }> {
  try { return JSON.parse(localStorage.getItem(PLACE_CACHE) ?? "{}") } catch { return {} }
}

/**
 * The exact place around a point, e.g. "Muhammad Hadi Street 78, Baku". Used only for the visitor's own position.
 * Answers are cached per ~100 m square in the browser, as the Nominatim usage policy requires.
 */
export async function exactPlace(lat: number, lon: number, city: string, signal?: AbortSignal) {
  const cell = `${lat.toFixed(4)},${lon.toFixed(4)}|${city}`
  const cache = cachedPlaces()
  if (cache[cell]) return cache[cell]
  const ask = async (zoom: number, dLat = 0, dLon = 0) => {
    const params = new URLSearchParams({
      format: "jsonv2", lat: (lat + dLat).toFixed(4), lon: (lon + dLon).toFixed(4), zoom: String(zoom),
      addressdetails: "1", "accept-language": "en",
    })
    let res = await fetch(`${OSM_REVERSE}?${params}`, { signal: signal ?? AbortSignal.timeout(6000) })
    if (res.status === 429) {  // asked too quickly: wait out the limit and try once more
      await new Promise((r) => setTimeout(r, 1500))
      res = await fetch(`${OSM_REVERSE}?${params}`, { signal: signal ?? AbortSignal.timeout(6000) })
    }
    if (!res.ok) return undefined
    const body = await res.json()
    return { ...(body.address as Record<string, string>), _type: String(body.type ?? '') } as Record<string, string>
  }
  // Streets people name their address by, ahead of motorways and main roads
  const rank = (type = "") => (["residential", "living_street", "unclassified", "service", "pedestrian"].includes(type) ? 0
    : ["tertiary", "secondary"].includes(type) ? 1 : 2)
  // A lookup only reports a street when the point is almost on it, so look around: ~100 m, then ~250 m
  const AROUND = [[0.0009, 0], [0, 0.0012], [-0.0009, 0], [0, -0.0012],
                  [0.0022, 0], [0, 0.0029], [-0.0022, 0], [0, -0.0029]]
  const pause = (ms: number) => new Promise((r) => setTimeout(r, ms))
  try {
    // Building level first, for the house number; then a wider look at the same point.
    // OpenStreetMap allows one request per second, so every extra look waits its turn.
    let address = await ask(18)
    if (!address?.road) { await pause(1100); address = (await ask(17)) ?? address }
    let nearby = false
    if (!address?.road) {
      const probes = []
      for (const [dLat, dLon] of AROUND) {
        await pause(1100)
        const probe = await ask(17, dLat, dLon)
        if (probe?.road) probes.push(probe)
        if (probes.length >= 2) break  // enough to choose a sensible one
      }
      const best = probes.sort((a, b) => rank(a._type) - rank(b._type))[0]
      if (best) { address = { ...address, road: best.road, house_number: "" }; nearby = true }
    }
    if (!address) return null
    // The street plus the city is exact: "Muhammad Hadi Street, Baku". District names in OpenStreetMap often
    // disagree with local usage (the area around Həzi Aslanov metro is mapped as Ahmedli), so they are used
    // only when no street is known.
    const small = neighbourhood(address, city)
    const exact = [address.road, address.house_number].filter(Boolean).join(" ")
    const name = address.road
      ? (nearby ? [`near ${address.road}`, small, city] : [exact, city]).filter(Boolean).join(", ")
      : [small, city].filter(Boolean).join(", ")
    if (name === city) return null  // nothing more exact than what SkyMate already knows
    const place = { name, detail: "", country: (address.country_code ?? "").toUpperCase() }
    try {
      const entries = Object.entries({ ...cache, [cell]: place }).slice(-60)  // keep the cache small
      localStorage.setItem(PLACE_CACHE, JSON.stringify(Object.fromEntries(entries)))
    } catch { /* storage unavailable */ }
    return place
  } catch {
    return null  // offline or blocked: the city name from SkyMate's own data stays
  }
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

export function title(now: { condition: Condition; is_day: boolean; description: string }) {
  if (now.condition === "Clear" && !now.is_day) return "Clear Night"
  if (now.condition === "Clouds") {
    const d = now.description.toLowerCase()
    if (d.includes("few") || d.includes("scattered")) return "Partly Cloudy"
    if (d.includes("overcast")) return "Overcast"
  }
  return CONDITION_TITLE[now.condition] ?? "Weather"
}

export function summary(d: Dashboard, u: Units) {
  return d.daily[0] ? daySummary(d.daily[0], "Today", u, d.uv.max_today) : ""
}

/** One-line outlook for a day; `when` is "Today", "Tomorrow" or a weekday name. */
export function daySummary(today: Day, when: string, u: Units, uvMax: number | null = today.uv_max ?? null) {
  const max = fmt.temp(today.max, u)
  const rain = today.precipitation ?? 0
  const On = when === "Today" || when === "Tomorrow" ? when : `On ${when}`
  switch (today.condition) {
    case "Thunderstorm":
      return `${On}, expect thunderstorms with temperatures reaching a maximum of ${max}. Stay indoors during lightning and avoid open areas.`
    case "Rain":
      return `${On}, expect a rainy day with temperatures reaching a maximum of ${max}. Grab your umbrella and raincoat before heading out.`
    case "Drizzle":
      return `${On}, expect light drizzle and a maximum of ${max}. A light jacket and an umbrella will keep you comfortable.`
    case "Snow":
      return `${On}, expect snow with a maximum of ${max}. Allow extra time for travel and dress in warm layers.`
    case "Fog":
    case "Mist":
      return `${On}, expect reduced visibility and a maximum of ${max}. Take extra care on the roads.`
    case "Clear":
      return `${On}, expect clear skies with temperatures reaching a maximum of ${max}.${(uvMax ?? 0) >= 6 ? " UV is high, so use sun protection." : " A great day to be outside."}`
    default:
      return `${On}, expect ${today.description || "clouds"} with a maximum of ${max}.${rain >= 1 ? " Keep an umbrella handy." : ""}`
  }
}

export function feelsNote(v: { temperature: number | null; feels_like: number | null; humidity: number | null; wind_speed: number | null }) {
  const { temperature: t, feels_like: f, humidity: h, wind_speed: w } = v
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

const regionNames = (() => {
  try { return new Intl.DisplayNames([locale], { type: "region" }) } catch { return null }
})()

export function countryName(code: string) {
  try { return (code && regionNames?.of(code.toUpperCase())) || code } catch { return code }
}
