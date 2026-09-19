import { useEffect, useRef, type CSSProperties } from "react"

import { Particles } from "@/components/ui/particles"
import type { Condition } from "@/lib/weather"
import { cn } from "@/lib/utils"

const GRADIENTS: Record<string, string> = {
  "Clear-day": "from-sky-400 via-sky-500 to-blue-800",
  "Clear-night": "from-indigo-950 via-slate-950 to-black",
  "Clouds-day": "from-sky-500 via-slate-500 to-slate-800",
  "Clouds-night": "from-slate-800 via-slate-900 to-black",
  "Rain-day": "from-slate-600 via-slate-700 to-slate-900",
  "Rain-night": "from-slate-800 via-slate-900 to-black",
  "Drizzle-day": "from-slate-500 via-slate-600 to-slate-900",
  "Drizzle-night": "from-slate-800 via-slate-900 to-black",
  "Thunderstorm-day": "from-slate-700 via-indigo-950 to-black",
  "Thunderstorm-night": "from-slate-900 via-indigo-950 to-black",
  "Snow-day": "from-slate-300 via-slate-400 to-slate-700",
  "Snow-night": "from-slate-700 via-slate-900 to-black",
  "Mist-day": "from-slate-400 via-slate-500 to-slate-800",
  "Mist-night": "from-slate-700 via-slate-900 to-black",
  "Fog-day": "from-slate-400 via-slate-500 to-slate-800",
  "Fog-night": "from-slate-700 via-slate-900 to-black",
}

/* ─── Rain (canvas) ────────────────────────────────────────────────────────── */

export function RainCanvas({ intensity, lightning, running }: { intensity: number; lightning: boolean; running: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    let width = 0, height = 0, frame = 0, flash = 0
    type Drop = { x: number; y: number; len: number; speed: number; alpha: number; w: number }
    let drops: Drop[] = []
    const spawn = (anywhere: boolean): Drop => {
      const near = Math.random() < 0.18
      return {
        x: Math.random() * (width + 300) - 150,
        y: anywhere ? Math.random() * height : -60,
        len: near ? 38 + Math.random() * 30 : 16 + Math.random() * 22,
        speed: near ? 20 + Math.random() * 8 : 11 + Math.random() * 8,
        alpha: near ? 0.35 + Math.random() * 0.25 : 0.2 + Math.random() * 0.3,
        w: near ? 1.6 : 1,
      }
    }
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const count = Math.round((width * height) / 5000 * intensity)
      drops = Array.from({ length: Math.min(count, 700) }, () => spawn(true))
    }
    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    resize()
    const slant = 0.2
    const tick = () => {
      ctx.clearRect(0, 0, width, height)
      if (lightning) {
        if (flash <= 0 && Math.random() < 0.004) flash = 1
        if (flash > 0) {
          ctx.fillStyle = `rgba(215, 228, 255, ${flash * 0.35})`
          ctx.fillRect(0, 0, width, height)
          flash -= 0.05
        }
      }
      ctx.lineCap = "round"
      for (const d of drops) {
        ctx.strokeStyle = `rgba(210, 228, 255, ${d.alpha})`
        ctx.lineWidth = d.w
        ctx.beginPath()
        ctx.moveTo(d.x, d.y)
        ctx.lineTo(d.x - d.len * slant, d.y + d.len)
        ctx.stroke()
        d.y += d.speed
        d.x -= d.speed * slant
        if (d.y > height + 60) Object.assign(d, spawn(false))
      }
      frame = requestAnimationFrame(tick)
    }
    if (running) {
      frame = requestAnimationFrame(tick)
    } else {
      tick() // draw one still frame, then stop
      cancelAnimationFrame(frame)
    }
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [intensity, lightning, running])

  return <canvas ref={ref} aria-hidden="true" className="absolute inset-0 h-full w-full" />
}

/* ─── Sun ──────────────────────────────────────────────────────────────────── */

function Sun({ dim = false }: { dim?: boolean }) {
  return (
    <div className={cn("absolute -top-[18vmin] right-[-12vmin] size-[80vmin] sm:right-[2vw]", dim && "opacity-60")}>
      <div className="sky-spin absolute inset-0 rounded-full opacity-70
        bg-[repeating-conic-gradient(from_0deg,rgba(255,236,170,0.55)_0deg_4deg,transparent_4deg_18deg)]
        [mask-image:radial-gradient(circle,black_18%,transparent_68%)]" />
      <div className="sky-spin-reverse absolute inset-[8%] rounded-full opacity-50
        bg-[repeating-conic-gradient(from_9deg,rgba(255,220,130,0.5)_0deg_2deg,transparent_2deg_14deg)]
        [mask-image:radial-gradient(circle,black_20%,transparent_62%)]" />
      <div className="sky-pulse absolute inset-[18%] rounded-full bg-[radial-gradient(circle,rgba(255,244,200,0.95)_0%,rgba(255,206,84,0.55)_35%,rgba(255,170,40,0)_70%)]" />
      <div className="absolute inset-[37%] rounded-full bg-[radial-gradient(circle_at_40%_40%,#fffbe8,#ffe07a_55%,#ffc53d)] shadow-[0_0_120px_40px_rgba(255,214,100,0.55)]" />
    </div>
  )
}

function SunBeams() {
  return (
    <div className="absolute inset-0 overflow-hidden">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="sky-beam absolute -top-1/4 right-[10%] h-[160%] w-[22vmin] origin-top bg-gradient-to-b from-amber-100/25 via-amber-50/10 to-transparent blur-2xl"
          style={{ rotate: `${28 + i * 14}deg`, animationDelay: `${-i * 4}s`, animationDuration: `${12 + i * 3}s` }}
        />
      ))}
    </div>
  )
}

/* ─── Clouds ───────────────────────────────────────────────────────────────── */

function CloudShape({ className, style }: { className?: string; style?: CSSProperties }) {
  return (
    <svg viewBox="0 0 320 140" className={className} style={style}>
      <g fill="currentColor">
        <ellipse cx="90" cy="92" rx="72" ry="42" />
        <ellipse cx="160" cy="70" rx="80" ry="58" />
        <ellipse cx="236" cy="94" rx="70" ry="40" />
        <rect x="40" y="92" width="240" height="40" rx="20" />
      </g>
    </svg>
  )
}

function Clouds({ tone, count, speed = 1 }: { tone: string; count: number; speed?: number }) {
  const layout = [
    { top: 6, size: 46, dur: 90, delay: 0 },
    { top: 22, size: 34, dur: 120, delay: -40 },
    { top: 40, size: 56, dur: 150, delay: -90 },
    { top: 12, size: 28, dur: 75, delay: -20 },
    { top: 58, size: 40, dur: 130, delay: -60 },
    { top: 30, size: 62, dur: 170, delay: -120 },
  ]
  return (
    <div className="absolute inset-0 overflow-hidden">
      {layout.slice(0, count).map((c, i) => (
        <CloudShape
          key={i}
          className={cn("sky-cloud-move absolute left-0 blur-[2px]", tone)}
          style={{ top: `${c.top}%`, width: `${c.size}vw`, animationDuration: `${c.dur / speed}s`, animationDelay: `${c.delay / speed}s` }}
        />
      ))}
    </div>
  )
}

/* ─── Night ────────────────────────────────────────────────────────────────── */

function Moon() {
  return (
    <div className="absolute top-[8vh] right-[10vw] size-[18vmin] min-h-24 min-w-24">
      <div className="sky-pulse absolute -inset-[60%] rounded-full bg-[radial-gradient(circle,rgba(210,225,255,0.35)_0%,rgba(210,225,255,0)_65%)]" />
      <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_35%_35%,#f8fbff,#d8e2f3_60%,#aab8d4)] shadow-[0_0_60px_10px_rgba(200,215,255,0.35)]" />
      <div className="absolute top-[28%] left-[52%] size-[16%] rounded-full bg-slate-400/25" />
      <div className="absolute top-[55%] left-[30%] size-[11%] rounded-full bg-slate-400/20" />
    </div>
  )
}

/* ─── Scene ────────────────────────────────────────────────────────────────── */

export function Sky({ condition, isDay, paused, active = true, cloudCover = 50 }: {
  condition: Condition
  isDay: boolean
  paused: boolean
  active?: boolean
  cloudCover?: number | null
}) {
  const gradient = GRADIENTS[`${condition}-${isDay ? "day" : "night"}`] ?? GRADIENTS["Clouds-day"]
  const rainy = condition === "Rain" || condition === "Drizzle" || condition === "Thunderstorm"
  const partly = condition === "Clouds" && (cloudCover ?? 50) < 75
  const running = !paused && active

  return (
    <div aria-hidden="true" data-paused={!running || undefined}
      className={cn("sky fixed inset-0 -z-10 overflow-hidden bg-gradient-to-b transition-colors duration-1000", gradient)}>
      {condition === "Clear" && isDay && (
        <>
          <SunBeams />
          <Sun />
          {!paused && <Particles className="absolute inset-0" quantity={60} staticity={80} ease={80} size={1.1} color="#fff3c4" vy={-0.08} />}
        </>
      )}

      {condition === "Clear" && !isDay && (
        <>
          {!paused && <Particles className="absolute inset-0" quantity={220} staticity={95} ease={90} size={0.7} color="#e3ecff" />}
          <div className="sky-twinkle absolute inset-0 bg-[radial-gradient(1px_1px_at_20%_30%,white,transparent),radial-gradient(1px_1px_at_70%_20%,white,transparent),radial-gradient(1.5px_1.5px_at_40%_60%,white,transparent),radial-gradient(1px_1px_at_85%_55%,white,transparent),radial-gradient(1.5px_1.5px_at_10%_75%,white,transparent)]" />
          <Moon />
        </>
      )}

      {condition === "Clouds" && (
        <>
          {partly && isDay && <Sun dim />}
          {partly && !isDay && <Moon />}
          <Clouds tone={isDay ? "text-white/70" : "text-slate-400/30"} count={partly ? 4 : 6} />
        </>
      )}

      {rainy && (
        <>
          <Clouds tone={condition === "Thunderstorm" ? "text-slate-900/70" : "text-slate-800/60"} count={6} speed={1.6} />
          <div className="absolute inset-0 bg-gradient-to-b from-slate-900/30 via-transparent to-slate-900/40" />
          {!paused && (
            <RainCanvas intensity={condition === "Drizzle" ? 0.5 : condition === "Thunderstorm" ? 1.4 : 1} lightning={condition === "Thunderstorm"} running={active} />
          )}
          <div className="sky-mist absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-slate-300/15 to-transparent" />
        </>
      )}

      {condition === "Snow" && (
        <>
          <Clouds tone={isDay ? "text-white/60" : "text-slate-400/30"} count={5} speed={0.8} />
          {!paused && <Particles className="absolute inset-0" quantity={220} staticity={60} ease={50} size={1.8} color="#ffffff" vy={0.7} vx={0.15} />}
        </>
      )}

      {(condition === "Mist" || condition === "Fog") && (
        <>
          <Clouds tone="text-slate-100/40" count={6} speed={0.6} />
          <div className="sky-mist absolute inset-0 bg-[linear-gradient(180deg,transparent_0%,rgba(226,232,240,0.25)_45%,rgba(226,232,240,0.35)_100%)]" />
        </>
      )}

      {/* keeps text readable further down the page */}
      <div className="absolute inset-x-0 bottom-0 h-[40vh] bg-gradient-to-b from-transparent to-[#0b1220]" />
    </div>
  )
}

/** Light rain drawn in front of the page content, as in rain running over glass. */
export function ForegroundRain({ condition, paused, active }: { condition: Condition; paused: boolean; active: boolean }) {
  const rainy = condition === "Rain" || condition === "Drizzle" || condition === "Thunderstorm"
  if (!rainy || paused) return null
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-30 opacity-45">
      <RainCanvas intensity={condition === "Drizzle" ? 0.12 : 0.25} lightning={false} running={active} />
    </div>
  )
}
