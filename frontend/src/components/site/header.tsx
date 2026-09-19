import { useState } from "react"
import { Menu, Pause, Play, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { Units } from "@/lib/weather"
import { cn } from "@/lib/utils"

export const NAV = [
  { href: "/#features", label: "Features" },
  { href: "/#pricing", label: "Pricing" },
  { href: "/#app", label: "Desktop App" },
  { href: "/#developers", label: "Developers" },
  { href: "/#faq", label: "FAQ" },
]

export function Logo() {
  return (
    <a href="/" className="flex items-center gap-2.5 rounded-lg text-white outline-none focus-visible:ring-2 focus-visible:ring-sky-300" translate="no">
      <img src="/favicon.svg" alt="" width={30} height={30} className="size-[30px]" />
      <span className="text-lg font-semibold tracking-tight">SkyMate</span>
    </a>
  )
}

export function Header({ units, setUnits, paused, setPaused, bot }: {
  units: Units
  setUnits: (u: Units) => void
  paused: boolean
  setPaused: (p: boolean) => void
  bot: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-slate-950/55 pt-[env(safe-area-inset-top)] backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">
        <Logo />
        <nav aria-label="Main" className="ml-4 hidden items-center gap-1 lg:flex">
          {NAV.map((n) => (
            <a key={n.href} href={n.href}
              className="rounded-lg px-3 py-2 text-sm text-white/70 transition-colors hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-sky-300 outline-none">
              {n.label}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <div role="group" aria-label="Units" className="flex rounded-full border border-white/15 bg-white/5 p-0.5">
            {(["metric", "imperial"] as const).map((u) => (
              <button key={u} type="button" aria-pressed={units === u} onClick={() => setUnits(u)}
                className={cn("rounded-full px-3 py-1 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-300",
                  units === u ? "bg-white text-slate-900" : "text-white/70 hover:text-white")}>
                {u === "metric" ? "°C" : "°F"}
              </button>
            ))}
          </div>
          <Button type="button" size="icon" variant="ghost" onClick={() => setPaused(!paused)}
            aria-label={paused ? "Play background animation" : "Pause background animation"} aria-pressed={paused}
            className="hidden rounded-full text-white/80 hover:bg-white/10 hover:text-white sm:inline-flex">
            {paused ? <Play aria-hidden="true" /> : <Pause aria-hidden="true" />}
          </Button>
          <Button asChild className="hidden rounded-full bg-sky-400 text-slate-950 hover:bg-sky-300 sm:inline-flex">
            <a href={`https://t.me/${bot}`} rel="noopener noreferrer" target="_blank">Open in Telegram</a>
          </Button>
          <Button type="button" size="icon" variant="ghost" aria-label={open ? "Close menu" : "Open menu"} aria-expanded={open}
            aria-controls="mobile-nav" onClick={() => setOpen(!open)}
            className="rounded-full text-white hover:bg-white/10 lg:hidden">
            {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          </Button>
        </div>
      </div>
      {open && (
        <nav id="mobile-nav" aria-label="Main" className="border-t border-white/10 px-4 pb-4 lg:hidden">
          <ul className="grid gap-1 pt-2">
            {NAV.map((n) => (
              <li key={n.href}>
                <a href={n.href} onClick={() => setOpen(false)}
                  className="block rounded-xl px-3 py-3 text-base text-white/85 hover:bg-white/10 outline-none focus-visible:ring-2 focus-visible:ring-sky-300">
                  {n.label}
                </a>
              </li>
            ))}
            <li className="flex gap-2 pt-2 sm:hidden">
              <Button asChild className="flex-1 rounded-full bg-sky-400 text-slate-950 hover:bg-sky-300">
                <a href={`https://t.me/${bot}`} rel="noopener noreferrer" target="_blank">Open in Telegram</a>
              </Button>
              <Button type="button" variant="outline" onClick={() => setPaused(!paused)} aria-pressed={paused}
                className="rounded-full border-white/20 bg-transparent text-white hover:bg-white/10">
                {paused ? "Play Animation" : "Pause Animation"}
              </Button>
            </li>
          </ul>
        </nav>
      )}
    </header>
  )
}
