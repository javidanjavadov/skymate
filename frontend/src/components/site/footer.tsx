import { Logo } from "@/components/site/header"

export function Footer({ bot }: { bot: string }) {
  const cols = [
    { title: "Product", links: [[`https://t.me/${bot}`, "Telegram Bot"], ["/#app", "Desktop App"], ["/#pricing", "Pricing"]] },
    { title: "Developers", links: [["/docs", "API Documentation"], ["/redoc", "API Reference"], ["/v1/status", "Service Status"]] },
    { title: "Legal", links: [["/terms", "Terms of Service"], ["/privacy", "Privacy Policy"], ["/owner", "Owner Sign-In"]] },
  ]
  return (
    <footer className="border-t border-white/10 bg-slate-950/90 pb-[env(safe-area-inset-bottom)]">
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div>
            <Logo />
            <p className="mt-3 max-w-xs text-pretty text-sm text-white/55">Weather you can trust: real measurements and global forecasts for every city.</p>
          </div>
          {cols.map((c) => (
            <nav key={c.title} aria-label={c.title}>
              <h2 className="text-sm font-semibold text-white">{c.title}</h2>
              <ul className="mt-3 space-y-2">
                {c.links.map(([href, label]) => (
                  <li key={href}>
                    <a href={href} {...(href.startsWith("http") ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                      className="rounded text-sm text-white/60 outline-none hover:text-white focus-visible:ring-2 focus-visible:ring-sky-300">{label}</a>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="mt-10 flex flex-col gap-3 border-t border-white/10 pt-6 text-xs text-white/45 sm:flex-row sm:justify-between">
          <p>© {new Date().getFullYear()} <span translate="no">SkyMate</span>. All rights reserved.</p>
          <p className="text-pretty">Forecast data: NOAA GFS (public domain), ECMWF open data (CC BY 4.0). Places: GeoNames (CC BY 4.0).</p>
        </div>
      </div>
    </footer>
  )
}
