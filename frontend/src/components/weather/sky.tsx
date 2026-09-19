import { useCallback, useEffect, useRef, useState } from "react"

import type { Condition } from "@/lib/weather"
import { cn } from "@/lib/utils"

export type SkyScene = { condition: Condition; isDay: boolean; cloudCover?: number | null }

/* ─── Canvas engine ────────────────────────────────────────────────────────── */

type Painter = { resize: (w: number, h: number) => void; frame: (ctx: CanvasRenderingContext2D, w: number, h: number, t: number, dt: number) => void }

function SceneCanvas({ create, running, className }: { create: () => Painter; running: boolean; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext("2d")
    if (!canvas || !ctx) return
    const painter = create()
    let w = 0, h = 0, raf = 0, last = performance.now()
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      painter.resize(w, h)
      if (!running) { ctx.clearRect(0, 0, w, h); painter.frame(ctx, w, h, performance.now(), 0) }
    }
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    resize()
    const loop = (now: number) => {
      const dt = Math.min(50, now - last)
      last = now
      ctx.clearRect(0, 0, w, h)
      painter.frame(ctx, w, h, now, dt)
      raf = requestAnimationFrame(loop)
    }
    if (running) raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); ro.disconnect() }
  }, [create, running])
  return <canvas ref={ref} aria-hidden="true" className={cn("absolute inset-0 h-full w-full", className)} />
}

const rand = (a: number, b: number) => a + Math.random() * (b - a)

function rainPainter(intensity: number, lightning: boolean): Painter {
  const layers = [
    { share: 0.5, len: [10, 18], speed: [9, 12], alpha: [0.12, 0.22], width: 0.8 },
    { share: 0.35, len: [18, 30], speed: [14, 18], alpha: [0.2, 0.34], width: 1.1 },
    { share: 0.15, len: [32, 52], speed: [22, 28], alpha: [0.3, 0.48], width: 1.6 },
  ]
  type Drop = { x: number; y: number; len: number; speed: number; alpha: number; width: number }
  let drops: Drop[] = []
  let flash = 0, bolt: { pts: [number, number][]; life: number } | null = null
  const spawn = (l: typeof layers[number], w: number, h: number, anywhere: boolean): Drop => ({
    x: rand(-150, w + 150), y: anywhere ? rand(0, h) : rand(-120, -20),
    len: rand(l.len[0], l.len[1]), speed: rand(l.speed[0], l.speed[1]), alpha: rand(l.alpha[0], l.alpha[1]), width: l.width,
  })
  return {
    resize(w, h) {
      const total = Math.min(900, Math.round((w * h) / 3800 * intensity))
      drops = layers.flatMap((l) => Array.from({ length: Math.round(total * l.share) }, () => spawn(l, w, h, true)))
    },
    frame(ctx, w, h, t, dt) {
      const slant = 0.16 + Math.sin(t / 2600) * 0.06
      if (lightning && dt > 0) {
        if (flash <= 0 && Math.random() < dt / 7000) {
          flash = 1
          let x = rand(w * 0.15, w * 0.85), y = 0
          const pts: [number, number][] = [[x, y]]
          while (y < h * rand(0.45, 0.7)) { y += rand(18, 42); x += rand(-26, 26); pts.push([x, y]) }
          bolt = { pts, life: 1 }
        }
        if (flash > 0) {
          ctx.fillStyle = `rgba(200, 215, 255, ${flash * 0.28})`
          ctx.fillRect(0, 0, w, h)
          flash -= dt / 380
        }
        if (bolt && bolt.life > 0) {
          ctx.save()
          ctx.strokeStyle = `rgba(235, 242, 255, ${bolt.life})`
          ctx.shadowColor = "rgba(170, 195, 255, 0.9)"
          ctx.shadowBlur = 18
          ctx.lineWidth = 2
          ctx.beginPath()
          bolt.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
          ctx.stroke()
          ctx.restore()
          bolt.life -= dt / 260
        }
      }
      ctx.lineCap = "round"
      const step = dt / 16
      for (const d of drops) {
        ctx.strokeStyle = `rgba(214, 228, 245, ${d.alpha})`
        ctx.lineWidth = d.width
        ctx.beginPath()
        ctx.moveTo(d.x, d.y)
        ctx.lineTo(d.x - d.len * slant, d.y + d.len)
        ctx.stroke()
        d.y += d.speed * step
        d.x -= d.speed * slant * step
        if (d.y > h + 60) { d.y = rand(-120, -20); d.x = rand(-150, w + 250) }
      }
    },
  }
}

function snowPainter(): Painter {
  type Flake = { x: number; y: number; r: number; speed: number; sway: number; phase: number; alpha: number }
  let flakes: Flake[] = []
  return {
    resize(w, h) {
      const n = Math.min(420, Math.round((w * h) / 5200))
      flakes = Array.from({ length: n }, () => {
        const r = Math.random() < 0.15 ? rand(2.4, 3.6) : rand(0.8, 2)
        return { x: rand(0, w), y: rand(0, h), r, speed: r * 0.35, sway: rand(0.3, 1.1), phase: rand(0, Math.PI * 2), alpha: rand(0.55, 0.95) }
      })
    },
    frame(ctx, w, h, t, dt) {
      const step = dt / 16
      for (const f of flakes) {
        const x = f.x + Math.sin(t / 1400 + f.phase) * 12 * f.sway
        ctx.fillStyle = `rgba(255, 255, 255, ${f.alpha})`
        ctx.beginPath()
        ctx.arc(x, f.y, f.r, 0, Math.PI * 2)
        ctx.fill()
        f.y += f.speed * step
        f.x += 0.15 * step
        if (f.y > h + 8) { f.y = -8; f.x = rand(0, w) }
        if (f.x > w + 20) f.x = -20
      }
    },
  }
}

function starPainter(density = 1): Painter {
  type Star = { x: number; y: number; r: number; base: number; speed: number; phase: number }
  let stars: Star[] = []
  let shooting: { x: number; y: number; vx: number; vy: number; life: number } | null = null
  return {
    resize(w, h) {
      const n = Math.min(650, Math.round((w * h) / 2400 * density))
      stars = Array.from({ length: n }, () => ({
        x: rand(0, w), y: rand(0, h * 0.85), r: Math.random() < 0.08 ? rand(1.1, 1.6) : rand(0.3, 0.9),
        base: rand(0.35, 0.95), speed: rand(0.6, 1.8), phase: rand(0, Math.PI * 2),
      }))
    },
    frame(ctx, w, h, t, dt) {
      for (const s of stars) {
        const a = s.base * (0.65 + 0.35 * Math.sin(t / 1000 * s.speed + s.phase))
        ctx.fillStyle = `rgba(232, 240, 255, ${a})`
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fill()
      }
      if (dt > 0 && !shooting && Math.random() < dt / 9000) {
        shooting = { x: rand(w * 0.2, w), y: rand(0, h * 0.35), vx: -rand(9, 13), vy: rand(3, 5), life: 1 }
      }
      if (shooting) {
        const s = shooting
        const grad = ctx.createLinearGradient(s.x, s.y, s.x - s.vx * 9, s.y - s.vy * 9)
        grad.addColorStop(0, `rgba(255, 255, 255, ${s.life})`)
        grad.addColorStop(1, "rgba(255, 255, 255, 0)")
        ctx.strokeStyle = grad
        ctx.lineWidth = 1.6
        ctx.beginPath()
        ctx.moveTo(s.x, s.y)
        ctx.lineTo(s.x - s.vx * 9, s.y - s.vy * 9)
        ctx.stroke()
        s.x += s.vx * (dt / 16)
        s.y += s.vy * (dt / 16)
        s.life -= dt / 900
        if (s.life <= 0) shooting = null
      }
    },
  }
}

/* ─── Clouds: pre-rendered cumulus sprites drifting at three depths ───────── */

type CloudStyle = { light: string; shadow: string } // light is an "r,g,b" triplet
type CloudLayerSpec = { count: number; size: [number, number]; y: [number, number]; speed: number; alpha: number }

function makeCloud(w: number, style: CloudStyle): HTMLCanvasElement {
  const h = Math.round(w * 0.55)
  const c = document.createElement("canvas")
  // Render at screen resolution so clouds stay crisp on high-DPI displays
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  c.width = Math.round(w * dpr)
  c.height = Math.round(h * dpr)
  const g = c.getContext("2d")!
  g.scale(dpr, dpr)
  const puffs = 22 + Math.floor(Math.random() * 14)
  for (let i = 0; i < puffs; i++) {
    const x = rand(0.14, 0.86) * w
    const d = Math.abs(x - w / 2) / (w / 2)
    const r = w * (0.07 + 0.13 * (1 - d * d)) * rand(0.75, 1.1)
    const y = h * 0.78 - r * rand(0.25, 0.95)
    const grad = g.createRadialGradient(x, y, 0, x, y, r)
    grad.addColorStop(0, `rgba(${style.light},1)`)
    grad.addColorStop(0.96, `rgba(${style.light},1)`)
    grad.addColorStop(1, `rgba(${style.light},0)`)
    g.fillStyle = grad
    g.beginPath()
    g.arc(x, y, r, 0, Math.PI * 2)
    g.fill()
  }
  // Shade the underside so clouds read as volumes rather than flat shapes
  g.globalCompositeOperation = "source-atop"
  const shade = g.createLinearGradient(0, h * 0.2, 0, h)
  shade.addColorStop(0, "rgba(0,0,0,0)")
  shade.addColorStop(1, style.shadow)
  g.fillStyle = shade
  g.fillRect(0, 0, w, h)
  // Soft flat base
  g.globalCompositeOperation = "destination-out"
  const base = g.createLinearGradient(0, h * 0.7, 0, h * 0.92)
  base.addColorStop(0, "rgba(0,0,0,0)")
  base.addColorStop(1, "rgba(0,0,0,1)")
  g.fillStyle = base
  g.fillRect(0, 0, w, h)
  return c
}

function cloudPainter(style: CloudStyle, layers: CloudLayerSpec[]): Painter {
  type Cloud = { img: HTMLCanvasElement; w: number; h: number; x: number; y: number; speed: number; alpha: number }
  let clouds: Cloud[] = []
  return {
    resize(w, h) {
      clouds = layers.flatMap((l) => Array.from({ length: l.count }, (_, i) => {
        const cw = Math.round(Math.min(900, w * rand(l.size[0], l.size[1])) + 120)
        return {
          img: makeCloud(cw, style),
          w: cw,
          h: Math.round(cw * 0.55),
          x: ((i + rand(0, 0.8)) / l.count) * (w + cw) - cw,
          y: h * rand(l.y[0], l.y[1]) - cw * 0.3,
          speed: l.speed * rand(0.8, 1.2),
          alpha: l.alpha,
        }
      }))
    },
    frame(ctx, w, _h, _t, dt) {
      for (const c of clouds) {
        ctx.globalAlpha = c.alpha
        ctx.drawImage(c.img, c.x, c.y, c.w, c.h)
        c.x += c.speed * dt
        if (c.x > w + 20) c.x = -c.w - rand(0, 200)
      }
      ctx.globalAlpha = 1
    },
  }
}

const CLOUD_STYLES = {
  day: { light: "255,255,255", shadow: "rgba(118,138,168,0.75)" },
  grey: { light: "214,221,231", shadow: "rgba(96,108,128,0.85)" },
  night: { light: "92,106,132", shadow: "rgba(18,24,38,0.85)" },
  rain: { light: "84,95,114", shadow: "rgba(22,28,40,0.9)" },
  storm: { light: "58,66,84", shadow: "rgba(8,11,18,0.95)" },
} satisfies Record<string, CloudStyle>

const FEW: CloudLayerSpec[] = [
  { count: 3, size: [0.16, 0.24], y: [0.08, 0.3], speed: 0.006, alpha: 0.55 },
  { count: 2, size: [0.3, 0.42], y: [0.2, 0.45], speed: 0.012, alpha: 0.9 },
]
const BROKEN: CloudLayerSpec[] = [
  { count: 5, size: [0.2, 0.3], y: [0.0, 0.3], speed: 0.006, alpha: 0.7 },
  { count: 4, size: [0.34, 0.5], y: [0.12, 0.45], speed: 0.011, alpha: 0.9 },
  { count: 3, size: [0.5, 0.7], y: [0.35, 0.6], speed: 0.018, alpha: 1 },
]
const OVERCAST: CloudLayerSpec[] = [
  { count: 7, size: [0.3, 0.45], y: [-0.1, 0.25], speed: 0.008, alpha: 0.95 },
  { count: 6, size: [0.45, 0.65], y: [0.1, 0.45], speed: 0.014, alpha: 1 },
  { count: 4, size: [0.6, 0.85], y: [0.35, 0.65], speed: 0.022, alpha: 1 },
]

function Clouds({ style, layers, running }: { style: CloudStyle; layers: CloudLayerSpec[]; running: boolean }) {
  const create = useCallback(() => cloudPainter(style, layers), [style, layers])
  return <SceneCanvas create={create} running={running} />
}

function FogBands() {
  return (
    <>
      {["top-[18%]", "top-[42%]", "top-[64%]"].map((pos, i) => (
        <div key={pos} className={cn("sky-drift absolute -inset-x-1/4 h-[28%] bg-gradient-to-r from-transparent via-white/45 to-transparent blur-md", pos)}
          style={{ animationDelay: `${-i * 5}s`, animationDuration: `${16 + i * 6}s` }} />
      ))}
    </>
  )
}

function Sun({ strength = 1 }: { strength?: number }) {
  return (
    <div className="absolute top-[4%] right-[8%] size-0" style={{ opacity: strength }}>
      <div className="sky-breathe absolute -translate-1/2 size-[110vmin] rounded-full bg-[radial-gradient(circle,rgba(255,236,190,0.5)_0%,rgba(255,214,140,0.16)_16%,rgba(255,200,120,0)_40%)]" />
      <div className="absolute -translate-1/2 size-[28vmin] rounded-full bg-[radial-gradient(circle,rgba(255,250,235,1)_0%,rgba(255,238,190,0.85)_25%,rgba(255,220,150,0)_70%)]" />
      <div className="absolute -translate-1/2 size-[7vmin] min-h-12 min-w-12 rounded-full bg-[#fffdf5] shadow-[0_0_60px_20px_rgba(255,244,210,0.9)]" />
      {/* lens flare ghosts along the diagonal */}
      <div className="sky-flare absolute left-[-30vmin] top-[22vmin] size-[9vmin] rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.18),transparent_70%)]" />
      <div className="sky-flare absolute left-[-52vmin] top-[40vmin] size-[4vmin] rounded-full bg-[radial-gradient(circle,rgba(190,220,255,0.28),transparent_70%)] [animation-delay:-3s]" />
      <div className="sky-flare absolute left-[-74vmin] top-[58vmin] size-[14vmin] rounded-full border border-white/10 bg-[radial-gradient(circle,rgba(255,230,200,0.08),transparent_70%)] [animation-delay:-6s]" />
    </div>
  )
}

function Moon({ strength = 1 }: { strength?: number }) {
  return (
    <div className="absolute top-[9%] right-[12%] size-0" style={{ opacity: strength }}>
      <div className="sky-breathe absolute -translate-1/2 size-[60vmin] rounded-full bg-[radial-gradient(circle,rgba(200,215,255,0.22)_0%,rgba(200,215,255,0)_55%)]" />
      <div className="absolute -translate-1/2 size-[9vmin] min-h-16 min-w-16 rounded-full bg-[radial-gradient(circle_at_38%_35%,#fbfdff,#dfe7f5_55%,#b7c4dc)] shadow-[0_0_50px_12px_rgba(205,220,255,0.35)]" />
    </div>
  )
}

/* ─── Scenes ───────────────────────────────────────────────────────────────── */

const LOADING_GRADIENT = "linear-gradient(180deg,#0b1220 0%,#111c33 55%,#0b1220 100%)"

function sceneGradient(s: SkyScene | null): string {
  if (!s) return LOADING_GRADIENT
  const day = s.isDay
  switch (s.condition) {
    case "Clear": return day ? "linear-gradient(180deg,#1760c4 0%,#2f85e0 38%,#7dbcf0 72%,#b9dcf6 100%)" : "linear-gradient(180deg,#040817 0%,#0a1433 45%,#1a2a55 100%)"
    case "Clouds": return day ? "linear-gradient(180deg,#56779e 0%,#7a95b5 45%,#a9bacc 100%)" : "linear-gradient(180deg,#0c1220 0%,#1a2233 55%,#2b3547 100%)"
    case "Rain": case "Drizzle": return day ? "linear-gradient(180deg,#27313f 0%,#3a4657 50%,#56657a 100%)" : "linear-gradient(180deg,#0b0f17 0%,#161d29 55%,#252e3d 100%)"
    case "Thunderstorm": return day ? "linear-gradient(180deg,#141a26 0%,#212a3a 50%,#343f53 100%)" : "linear-gradient(180deg,#07090f 0%,#10151f 55%,#1d2433 100%)"
    case "Snow": return day ? "linear-gradient(180deg,#7f92a9 0%,#a3b3c5 50%,#cdd7e2 100%)" : "linear-gradient(180deg,#141b27 0%,#253042 55%,#394659 100%)"
    default: return day ? "linear-gradient(180deg,#76808d 0%,#98a1ab 50%,#bcc3ca 100%)" : "linear-gradient(180deg,#121720 0%,#222935 55%,#343c49 100%)"
  }
}

function Scene({ scene, running }: { scene: SkyScene | null; running: boolean }) {
  const c = scene?.condition
  const day = scene?.isDay ?? true
  const rainy = c === "Rain" || c === "Drizzle" || c === "Thunderstorm"
  const partly = c === "Clouds" && (scene?.cloudCover ?? 60) < 75
  const rain = useCallback(() => rainPainter(c === "Drizzle" ? 0.55 : c === "Thunderstorm" ? 1.3 : 1, c === "Thunderstorm"), [c])
  const stars = useCallback(() => starPainter(c === "Clear" ? 1 : 0.35), [c])
  const snow = useCallback(() => snowPainter(), [])

  return (
    <div className="absolute inset-0" style={{ background: sceneGradient(scene) }} data-paused={!running || undefined}>
      {c === "Clear" && day && (
        <>
          <Sun />
          <Clouds style={CLOUD_STYLES.day} layers={FEW.slice(0, 1)} running={running} />
          <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-white/10 to-transparent" />
        </>
      )}
      {c === "Clear" && !day && (<><SceneCanvas create={stars} running={running} /><Moon /></>)}

      {c === "Clouds" && (
        <>
          {!day && <SceneCanvas create={stars} running={running} />}
          {partly && (day ? <Sun strength={0.8} /> : <Moon strength={0.8} />)}
          <Clouds style={day ? (partly ? CLOUD_STYLES.day : CLOUD_STYLES.grey) : CLOUD_STYLES.night}
            layers={partly ? BROKEN : OVERCAST} running={running} />
        </>
      )}

      {rainy && (
        <>
          <Clouds style={c === "Thunderstorm" ? CLOUD_STYLES.storm : CLOUD_STYLES.rain} layers={OVERCAST} running={running} />
          <SceneCanvas create={rain} running={running} />
          <div className="sky-drift absolute inset-x-0 bottom-0 h-2/5 bg-gradient-to-t from-slate-300/20 to-transparent" />
        </>
      )}

      {c === "Snow" && (
        <>
          <Clouds style={day ? CLOUD_STYLES.grey : CLOUD_STYLES.night} layers={BROKEN} running={running} />
          <SceneCanvas create={snow} running={running} />
        </>
      )}

      {(c === "Mist" || c === "Fog") && (
        <>
          <Clouds style={day ? CLOUD_STYLES.grey : CLOUD_STYLES.night} layers={FEW} running={running} />
          <FogBands />
        </>
      )}

      {/* Page content below the dashboard stays readable */}
      <div className="absolute inset-x-0 bottom-0 h-[42vh] bg-gradient-to-b from-transparent to-[#0b1220]" />
    </div>
  )
}

function sceneKey(s: SkyScene | null) {
  if (!s) return "loading"
  const partly = s.condition === "Clouds" && (s.cloudCover ?? 60) < 75
  return `${s.condition}-${s.isDay ? "day" : "night"}-${partly ? "partly" : "full"}`
}

/** Background scene; cross-fades when the weather changes (including from the loading state). */
export function Sky({ scene, paused, active = true }: { scene: SkyScene | null; paused: boolean; active?: boolean }) {
  const key = sceneKey(scene)
  const [layers, setLayers] = useState<{ key: string; scene: SkyScene | null }[]>([{ key, scene }])

  useEffect(() => {
    setLayers((prev) => (prev[prev.length - 1].key === key ? prev : [...prev.slice(-1), { key, scene }]))
    const t = setTimeout(() => setLayers((prev) => prev.slice(-1)), 1800)
    return () => clearTimeout(t)
    // scene identity changes with every fetch; the key captures what's visible
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return (
    <div aria-hidden="true" className="sky fixed inset-0 -z-10 overflow-hidden bg-[#0b1220]">
      {layers.map((l, i) => {
        const current = i === layers.length - 1
        return (
          <div key={l.key} className={cn("absolute inset-0", current && layers.length > 1 && "sky-fade-in")}>
            <Scene scene={l.scene} running={current && !paused && active} />
          </div>
        )
      })}
    </div>
  )
}

/** Light rain drawn in front of the page content, like rain running over glass. */
export function ForegroundRain({ scene, paused, active }: { scene: SkyScene | null; paused: boolean; active: boolean }) {
  const c = scene?.condition
  const rainy = c === "Rain" || c === "Drizzle" || c === "Thunderstorm"
  const create = useCallback(() => rainPainter(c === "Drizzle" ? 0.1 : 0.2, false), [c])
  if (!rainy || paused) return null
  return (
    <div aria-hidden="true" className="sky-fade-in pointer-events-none fixed inset-0 z-30 opacity-40">
      <SceneCanvas create={create} running={active} />
    </div>
  )
}
