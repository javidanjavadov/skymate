import { Logo } from "@/components/site/header"
import { useT } from "@/lib/i18n"

export function Footer({ bot }: { bot: string }) {
  const { t } = useT()
  const cols = [
    { title: t("footer.product"), links: [[`https://t.me/${bot}`, t("nav.telegram")], ["/#pricing", t("nav.pricing")]] },
    { title: t("footer.developers"), links: [["/docs", t("footer.docs")], ["/redoc", t("footer.reference")], ["/v1/status", t("footer.status")]] },
    { title: t("footer.legal"), links: [["/terms", t("footer.terms")], ["/privacy", t("footer.privacy")]] },
  ]
  return (
    <footer className="border-t border-white/10 bg-slate-950/90 pb-[env(safe-area-inset-bottom)]">
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div>
            <Logo />
            <p className="mt-3 max-w-xs text-pretty text-sm text-white/55">{t("footer.tagline")}</p>
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
          <p>{t("footer.rights", { year: new Date().getFullYear() })}</p>
          <p className="text-pretty">{t("footer.sources")}</p>
        </div>
      </div>
    </footer>
  )
}
