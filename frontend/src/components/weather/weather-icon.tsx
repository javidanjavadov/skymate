import {
  Cloud, CloudDrizzle, CloudFog, CloudLightning, CloudMoon, CloudRain, CloudSnow, CloudSun, Moon, Sun,
  type LucideProps,
} from "lucide-react"

import type { Condition } from "@/lib/weather"
import { cn } from "@/lib/utils"

const ICONS = {
  Clear: { day: Sun, night: Moon, color: "text-amber-300" },
  Clouds: { day: CloudSun, night: CloudMoon, color: "text-slate-200" },
  Rain: { day: CloudRain, night: CloudRain, color: "text-sky-300" },
  Drizzle: { day: CloudDrizzle, night: CloudDrizzle, color: "text-sky-200" },
  Thunderstorm: { day: CloudLightning, night: CloudLightning, color: "text-yellow-200" },
  Snow: { day: CloudSnow, night: CloudSnow, color: "text-white" },
  Mist: { day: CloudFog, night: CloudFog, color: "text-slate-300" },
  Fog: { day: CloudFog, night: CloudFog, color: "text-slate-300" },
} satisfies Record<Condition, unknown>

export function WeatherIcon({ condition, isDay = true, className, ...props }: { condition: Condition; isDay?: boolean } & LucideProps) {
  const entry = ICONS[condition] ?? { day: Cloud, night: Cloud, color: "text-slate-200" }
  const Icon = isDay ? entry.day : entry.night
  return <Icon aria-hidden="true" className={cn(entry.color, className)} strokeWidth={1.6} {...props} />
}
