import { useEffect, useRef } from "react"

import { Particles } from "@/components/ui/particles"
import type { Condition } from "@/lib/weather"
import { cn } from "@/lib/utils"

const GRADIENTS: Record<string, string> = {
  "Clear-day": "from-sky-400 via-sky-600 to-blue-900",
  "Clear-night": "from-indigo-950 via-slate-950 to-black",
  "Clouds-day": "from-slate-400 via-slate-600 to-slate-800",
  "Clouds-night": "from-slate-800 via-slate-900 to-black",
  "Rain-day": "from-slate-500 via-blue-800 to-slate-900",
  "Rain-night": "from-slate-800 via-blue-950 to-black",
  "Drizzle-day": "from-slate-500 via-blue-800 to-slate-950",
  "Drizzle-night": "from-slate-800 via-blue-950 to-black",
  "Thunderstorm-day": "from-slate-700 via-indigo-950 to-black",
  "Thunderstorm-night": "from-slate-900 via-indigo-950 to-black",
  "Snow-day": "from-slate-300 via-slate-500 to-slate-800",
  "Snow-night": "from-slate-700 via-slate-900 to-black",
  "Mist-day": "from-slate-400 via-slate-600 to-slate-900",
  "Mist-night": "from-slate-700 via-slate-900 to-black",
  "Fog-day": "from-slate-400 via-slate-600 to-slate-900",
  "Fog-night": "from-slate-700 via-slate-900 to-black",
}

function RainCanvas({ intensity, lightning, running }: { intensity: number; lightning: boolean; running: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    let width = 0, height = 0, frame = 0, flash = 0
    type Drop = { x: number; y: number; len: number; speed: number; alpha: number }
    let drops: Drop[] = []
    const spawn = (anywhere: boolean): Drop => ({
      x: Math.random() * (width + 200) - 100,
      y: anywhere ? Math.random() * height : -40,
      len: 18 + Math.random() * 30,
      speed: 9 + Math.random() * 9,
      alpha: 0.18 + Math.random() * 0.34,
    })
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const count = Math.round((width * height) / 9000 * intensity)
      drops = Array.from({ length: Math.min(count, 600) }, () => spawn(true))
    }
    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    resize()
    const slant = 0.22
    const tick = () => {
      ctx.clearRect(0, 0, width, height)
      if (lightning) {
        if (flash <= 0 && Math.random() < 0.0025) flash = 1
        if (flash > 0) {
          ctx.fillStyle = `rgba(210, 225, 255, ${flash * 0.18})`
          ctx.fillRect(0, 0, width, height)
          flash -= 0.06
        }
      }
      ctx.lineCap = "round"
      ctx.lineWidth = 1.1
      for (const d of drops) {
        ctx.strokeStyle = `rgba(200, 220, 255, ${d.alpha})`
        ctx.beginPath()
        ctx.moveTo(d.x, d.y)
        ctx.lineTo(d.x - d.len * slant, d.y + d.len)
        ctx.stroke()
        d.y += d.speed
        d.x -= d.speed * slant
        if (d.y > height + 40) Object.assign(d, spawn(false))
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

function DriftingClouds({ dense }: { dense: boolean }) {
  return (
    <div aria-hidden="true" className="absolute inset-0 overflow-hidden">
      {[0, 1, 2, 3].slice(0, dense ? 4 : 3).map((i) => (
        <div
          key={i}
          className="sky-cloud absolute rounded-full bg-white/10 blur-3xl"
          style={{
            width: `${40 + i * 12}vw`,
            height: `${18 + i * 6}vw`,
            top: `${5 + i * 18}%`,
            left: `${-20 + i * 25}%`,
            animationDuration: `${70 + i * 25}s`,
            animationDelay: `${-i * 15}s`,
          }}
        />
      ))}
    </div>
  )
}

export function Sky({ condition, isDay, paused, active = true }: { condition: Condition; isDay: boolean; paused: boolean; active?: boolean }) {
  const gradient = GRADIENTS[`${condition}-${isDay ? "day" : "night"}`] ?? GRADIENTS["Clouds-day"]
  const rainy = condition === "Rain" || condition === "Drizzle" || condition === "Thunderstorm"
  return (
    <div aria-hidden="true" className={cn("fixed inset-0 -z-10 bg-gradient-to-b transition-colors duration-700", gradient)}>
      {!paused && rainy && (
        <RainCanvas intensity={condition === "Drizzle" ? 0.45 : condition === "Thunderstorm" ? 1.3 : 1} lightning={condition === "Thunderstorm"} running={active} />
      )}
      {!paused && condition === "Snow" && (
        <Particles className="absolute inset-0" quantity={160} staticity={70} ease={60} size={1.4} color="#ffffff" vy={0.5} vx={0.1} />
      )}
      {!paused && condition === "Clear" && !isDay && (
        <Particles className="absolute inset-0" quantity={140} staticity={90} ease={80} size={0.6} color="#dbe7ff" />
      )}
      {(condition === "Clouds" || condition === "Mist" || condition === "Fog" || rainy) && (
        <DriftingClouds dense={condition !== "Clouds"} />
      )}
      {condition === "Clear" && isDay && (
        <div className="absolute -top-40 right-[-10%] h-[36rem] w-[36rem] rounded-full bg-amber-200/25 blur-3xl" />
      )}
      {(condition === "Mist" || condition === "Fog") && <div className="absolute inset-0 bg-slate-200/10 backdrop-blur-[2px]" />}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,transparent_0%,rgba(2,6,23,0.35)_70%)]" />
      <div className="absolute inset-x-0 bottom-0 h-[45vh] bg-gradient-to-b from-transparent to-[#0b1220]" />
    </div>
  )
}
