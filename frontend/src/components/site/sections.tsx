import { useEffect, useState, type ReactNode } from "react"
import {
  AlertTriangle, ArrowRight, CalendarDays, Check, Code2, Map, Minus, Radio, Send, ShieldCheck, Sun, Terminal,
} from "lucide-react"

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { AnimatedShinyText } from "@/components/ui/animated-shiny-text"
import { BlurFade } from "@/components/ui/blur-fade"
import { BorderBeam } from "@/components/ui/border-beam"
import { Button } from "@/components/ui/button"
import { MagicCard } from "@/components/ui/magic-card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { getLanguage, translate, useT } from "@/lib/i18n"
import { fmt } from "@/lib/weather"
import { cn } from "@/lib/utils"

function SectionHead({ kicker, title, children, id }: { kicker: string; title: string; children?: ReactNode; id: string }) {
  return (
    <div className="mx-auto mb-10 max-w-2xl text-center sm:mb-14">
      <p className="text-sm font-semibold uppercase tracking-[0.16em] text-sky-300">{kicker}</p>
      <h2 id={id} className="mt-3 text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h2>
      {children && <p className="mt-4 text-pretty text-lg text-white/65">{children}</p>}
    </div>
  )
}

const glass = "rounded-3xl border border-white/10 bg-slate-950/30"

export function Stats() {
  const { t } = useT()
  // Last known numbers show instantly; fresh ones replace them when /v1/status answers
  const [s, setS] = useState<{ readings: number; stations: number; days: number } | null>(() => {
    try { return JSON.parse(localStorage.getItem("skymate-stats") ?? "null") } catch { return null }
  })
  useEffect(() => {
    const ctrl = new AbortController()
    fetch("/v1/status", { signal: ctrl.signal }).then((r) => r.json()).then((d) => {
      const until = d.offline_ready_until ? new Date(d.offline_ready_until).getTime() : null
      const next = {
        readings: d.observations?.readings ?? 0,
        stations: d.observations?.stations ?? 0,
        days: until ? Math.max(1, Math.round((until - Date.now()) / 86_400_000)) : 10,
      }
      setS(next)
      try { localStorage.setItem("skymate-stats", JSON.stringify(next)) } catch { /* not remembered */ }
    }).catch(() => {})
    return () => ctrl.abort()
  }, [])
  const items = [
    { label: t("stats.measurements"), value: s?.readings },
    { label: t("stats.stations"), value: s?.stations },
    { label: t("stats.days"), value: s?.days },
  ]
  return (
    <section aria-label="Service statistics" className={cn(glass, "grid grid-cols-2 lg:grid-cols-4 [&>*]:min-w-0 [&>*]:border-white/10 max-lg:[&>*:nth-child(-n+2)]:border-b max-lg:[&>*:nth-child(odd)]:border-r lg:[&>*:not(:first-child)]:border-l")}>
      {items.map((it) => (
        <div key={it.label} className="px-4 py-5 sm:px-6">
          <p className="text-2xl font-semibold tabular-nums text-white sm:text-3xl">
            {it.value ? fmt.number(it.value) : "—"}
          </p>
          <p className="text-sm text-white/60">{it.label}</p>
        </div>
      ))}
      <div className="px-4 py-5 sm:px-6">
        <p className="text-2xl font-semibold text-white sm:text-3xl">{t("stats.global")}</p>
        <p className="text-sm text-white/60">{t("stats.everyCity")}</p>
      </div>
    </section>
  )
}

const FEATURES = [
  { icon: Radio, key: "measure" }, { icon: CalendarDays, key: "forecast" }, { icon: AlertTriangle, key: "alerts" },
  { icon: Sun, key: "uv" }, { icon: Map, key: "maps" }, { icon: ShieldCheck, key: "reliable" },
] as const

export function Features() {
  const { t } = useT()
  return (
    <section id="features" aria-labelledby="features-title" className="scroll-mt-24">
      <SectionHead id="features-title" kicker={t("sec.features.kicker")} title={t("sec.features.title")}>
        {t("sec.features.lead")}
      </SectionHead>
      <ul role="list" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f, i) => (
          <li key={f.key} className="min-w-0">
            <BlurFade inView delay={0.05 * i} className="h-full">
              <MagicCard className="h-full rounded-3xl" gradientColor="rgba(125,190,255,0.10)" gradientFrom="#7cc7ff" gradientTo="#a78bfa">
                <div className="h-full rounded-3xl bg-slate-950/30 p-6">
                  <span className="grid size-11 place-items-center rounded-xl bg-sky-400/15 text-sky-300">
                    <f.icon aria-hidden="true" className="size-5" />
                  </span>
                  <h3 className="mt-4 text-lg font-semibold text-white">{t(`feat.${f.key}.title`)}</h3>
                  <p className="mt-1.5 text-pretty text-[15px] text-white/65">{t(`feat.${f.key}.text`)}</p>
                </div>
              </MagicCard>
            </BlurFade>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function Measured() {
  const { t } = useT()
  const steps = (["collect", "store", "deliver"] as const).map((k) => [t(`step.${k}.title`), t(`step.${k}.text`)])
  return (
    <section id="measured" aria-labelledby="measured-title" className={cn(glass, "grid scroll-mt-24 gap-10 p-6 sm:p-10 lg:grid-cols-2 lg:items-center")}>
      <div>
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-sky-300">{t("sec.measured.kicker")}</p>
        <h2 id="measured-title" className="mt-3 text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          {t("sec.measured.title")}
        </h2>
        <p className="mt-4 text-pretty text-lg text-white/65">{t("sec.measured.lead")}</p>
      </div>
      <ol className="space-y-4">
        {steps.map(([t, d], i) => (
          <li key={t} className="flex gap-4 rounded-2xl border border-white/10 bg-white/[0.04] p-4">
            <span className="grid size-9 shrink-0 place-items-center rounded-full bg-sky-400 font-semibold text-slate-950 tabular-nums">{i + 1}</span>
            <div><h3 className="font-semibold text-white">{t}</h3><p className="text-pretty text-[15px] text-white/65">{d}</p></div>
          </li>
        ))}
      </ol>
    </section>
  )
}

function Feature({ ok = true, children }: { ok?: boolean; children: ReactNode }) {
  return (
    <li className={cn("flex gap-2.5 py-1.5 text-[15px]", ok ? "text-white/85" : "text-white/45")}>
      {ok ? <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-emerald-300" />
        : <Minus aria-hidden="true" className="mt-0.5 size-4 shrink-0" />}
      <span>{children}{!ok && <span className="sr-only"> {translate(getLanguage(), "plan.notIncluded")}</span>}</span>
    </li>
  )
}

type Plan = { daily: number; per_minute: number; price_usd_month: number }
const API_PLANS = ["free", "starter", "pro", "business"] as const

export function Pricing({ bot, stars }: { bot: string; stars: number }) {
  const { t } = useT()
  const initial = new URLSearchParams(location.search).get("pricing") === "api" ? "api" : "personal"
  const [tab, setTab] = useState(initial)
  const [plans, setPlans] = useState<Record<string, Plan> | null>(null)
  useEffect(() => {
    if (tab !== "api" || plans) return
    fetch("/v1/plans").then((r) => r.json()).then((d) => setPlans(d.plans)).catch(() => {})
  }, [tab, plans])
  const change = (v: string) => {
    setTab(v)
    const url = new URL(location.href)
    if (v === "api") url.searchParams.set("pricing", "api")
    else url.searchParams.delete("pricing")
    history.replaceState(null, "", url)
  }
  return (
    <section id="pricing" aria-labelledby="pricing-title" className="scroll-mt-24">
      <SectionHead id="pricing-title" kicker={t("sec.pricing.kicker")} title={t("sec.pricing.title")}>{t("sec.pricing.lead")}</SectionHead>
      <Tabs value={tab} onValueChange={change} className="items-center">
        <TabsList className="mb-8 h-11 rounded-full bg-white/10 p-1">
          <TabsTrigger value="personal" className="rounded-full px-5 data-[state=active]:bg-white data-[state=active]:text-slate-900">{t("price.personal")}</TabsTrigger>
          <TabsTrigger value="api" className="rounded-full px-5 data-[state=active]:bg-white data-[state=active]:text-slate-900">{t("price.api")}</TabsTrigger>
        </TabsList>
        <TabsContent value="personal" className="w-full">
          <div className="mx-auto grid max-w-4xl gap-5 md:grid-cols-2">
            <div className={cn(glass, "flex flex-col p-7")}>
              <h3 className="text-lg font-semibold text-white">{t("price.free")}</h3>
              <p className="mt-2 text-4xl font-semibold text-white">$0</p>
              <p className="text-sm text-white/55">{t("price.foreverFree")}</p>
              <ul className="my-6 flex-1">
                <Feature>{t("plan.free.1")}</Feature>
                <Feature>{t("plan.free.2")}</Feature>
                <Feature>{t("plan.free.3")}</Feature>
                <Feature>{t("plan.free.4")}</Feature>
                <Feature>{t("plan.free.5")}</Feature>
                <Feature ok={false}>{t("plan.free.6")}</Feature>
                <Feature ok={false}>{t("plan.free.7")}</Feature>
              </ul>
              <Button asChild variant="outline" className="h-11 rounded-full border-white/20 bg-transparent text-white hover:bg-white/10">
                <a href={`https://t.me/${bot}`} target="_blank" rel="noopener noreferrer">{t("price.startFree")}</a>
              </Button>
            </div>
            <div className={cn(glass, "relative flex flex-col overflow-hidden border-sky-300/30 p-7")}>
              <BorderBeam size={120} duration={9} colorFrom="#7cc7ff" colorTo="#a78bfa" />
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-lg font-semibold text-white">⭐ Premium</h3>
                <span className="rounded-full bg-sky-400/20 px-2.5 py-1 text-xs font-medium text-sky-200">{t("price.popular")}</span>
              </div>
              <p className="mt-2 text-4xl font-semibold text-white tabular-nums">{stars}&nbsp;⭐ <span className="text-base font-normal text-white/55">{t("price.perMonth")}</span></p>
              <p className="text-sm text-white/55">{t("price.stars")}</p>
              <ul className="my-6 flex-1">
                <Feature>{t("plan.premium.1")}</Feature>
                <Feature>{t("plan.premium.2")}</Feature>
                <Feature>{t("plan.premium.3")}</Feature>
                <Feature>{t("plan.premium.4")}</Feature>
                <Feature>{t("plan.premium.5")}</Feature>
              </ul>
              <Button asChild className="h-11 rounded-full bg-sky-400 text-slate-950 hover:bg-sky-300">
                <a href={`https://t.me/${bot}?start=premium`} target="_blank" rel="noopener noreferrer">{t("price.getPremium")}</a>
              </Button>
            </div>
          </div>
        </TabsContent>
        <TabsContent value="api" className="w-full">
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4" aria-busy={!plans}>
            {API_PLANS.map((k) => {
              const p = plans?.[k]
              return (
                <div key={k} className={cn(glass, "relative flex flex-col overflow-hidden p-6", k === "pro" && "border-sky-300/30")}>
                  {k === "pro" && <BorderBeam size={100} duration={10} colorFrom="#7cc7ff" colorTo="#a78bfa" />}
                  <h3 className="text-lg font-semibold capitalize text-white">{k}</h3>
                  <p className="mt-2 text-3xl font-semibold text-white tabular-nums">
                    {p ? `$${p.price_usd_month}` : "…"} <span className="text-sm font-normal text-white/55">{t("price.perMonth")}</span>
                  </p>
                  <p className="text-sm text-white/55 tabular-nums">
                    {p ? t("price.requests", { daily: fmt.number(p.daily), minute: fmt.number(p.per_minute) }) : t("search.loading")}
                  </p>
                  <ul className="my-5 flex-1">{([1, 2, 3] as const).map((n) => <Feature key={n}>{t(`api.${k}.${n}` as Parameters<typeof t>[0])}</Feature>)}</ul>
                  <Button asChild variant={k === "pro" ? "default" : "outline"}
                    className={cn("h-10 rounded-full", k === "pro" ? "bg-sky-400 text-slate-950 hover:bg-sky-300" : "border-white/20 bg-transparent text-white hover:bg-white/10")}>
                    <a href="/docs">{t(k === "free" ? "price.readDocs" : "price.getStarted")}</a>
                  </Button>
                </div>
              )
            })}
          </div>
          <p className="mt-6 text-center text-sm text-white/55">{t("price.custom")}</p>
        </TabsContent>
      </Tabs>
    </section>
  )
}

export function TelegramBot({ bot }: { bot: string }) {
  const { t } = useT()
  const steps = [
    [t("tg.step1.title"), t("tg.step1.text", { bot })],
    [t("tg.step2.title"), t("tg.step2.text")],
    [t("tg.step3.title"), t("tg.step3.text")],
  ]
  const chat: [string, string][] = [
    ["me", "Baku"],
    ["bot", "📍 Baku, AZ · measured 20 min ago\n☀️ 24°, clear sky · feels like 23°\n💨 Wind 26 km/h N · 💧 65%"],
    ["me", "/week"],
    ["bot", "📅 Next days\nTue 27° / 24° ☀️\nWed 27° / 23° 🌤\nThu 24° / 23° ☁️"],
  ]
  return (
    <section id="telegram" aria-labelledby="telegram-title" className={cn(glass, "grid scroll-mt-24 gap-10 p-6 sm:p-10 lg:grid-cols-2 lg:items-center")}>
      <div className="min-w-0">
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-sky-300">{t("sec.tg.kicker")}</p>
        <h2 id="telegram-title" className="mt-3 text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          {t("sec.tg.title")}
        </h2>
        <p className="mt-4 text-pretty text-lg text-white/65">{t("sec.tg.lead")}</p>
        <ol className="mt-7 space-y-3">
          {steps.map(([t, d], i) => (
            <li key={t} className="flex gap-4 rounded-2xl border border-white/10 bg-white/[0.04] p-4">
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-sky-400 font-semibold text-slate-950 tabular-nums">{i + 1}</span>
              <div><h3 className="font-semibold text-white">{t}</h3><p className="text-pretty text-[15px] text-white/65">{d}</p></div>
            </li>
          ))}
        </ol>
        <div className="mt-7 flex flex-wrap gap-3">
          <Button asChild className="h-11 rounded-full bg-white px-6 text-slate-900 hover:bg-sky-100">
            <a href={`https://t.me/${bot}`} target="_blank" rel="noopener noreferrer"><Send aria-hidden="true" />{t("tg.open")}</a>
          </Button>
          <Button asChild variant="outline" className="h-11 rounded-full border-white/20 bg-transparent text-white hover:bg-white/10">
            <a href={`https://t.me/${bot}?start=premium`} target="_blank" rel="noopener noreferrer">{t("price.getPremium")}</a>
          </Button>
        </div>
      </div>

      {/* Example conversation */}
      <figure aria-label="Example conversation with the SkyMate bot"
        className="mx-auto w-full max-w-sm rounded-[2rem] border border-white/10 bg-slate-950/60 p-4 shadow-2xl">
        <figcaption className="flex items-center gap-3 border-b border-white/10 pb-3">
          <img src="/favicon.svg" alt="" width={36} height={36} className="size-9 rounded-full" />
          <div className="min-w-0">
            <p className="truncate font-medium text-white">SkyMate</p>
            <p className="text-xs text-sky-300">bot</p>
          </div>
        </figcaption>
        <div className="space-y-2 pt-4 text-[14px] leading-snug">
          {chat.map(([who, text], i) => (
            <p key={i}
              className={cn("w-fit max-w-[85%] whitespace-pre-line rounded-2xl px-3.5 py-2",
                who === "me" ? "ml-auto rounded-br-md bg-sky-500 text-white" : "rounded-bl-md bg-white/10 text-white/90")}>
              {text}
            </p>
          ))}
        </div>
      </figure>
    </section>
  )
}

export function Developers() {
  const { t } = useT()
  return (
    <section id="developers" aria-labelledby="dev-title" className="grid scroll-mt-24 gap-10 lg:grid-cols-2 lg:items-center">
      <div className="min-w-0">
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-sky-300">{t("sec.dev.kicker")}</p>
        <h2 id="dev-title" className="mt-3 text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          {t("sec.dev.title")}
        </h2>
        <p className="mt-4 text-pretty text-lg text-white/65">
          Forecasts, station measurements, warnings, UV, air quality, geocoding and map images through one consistent JSON API,
          with clear limits and provenance on every response.
        </p>
        <div className="mt-7 flex flex-wrap gap-3">
          <Button asChild className="h-11 rounded-full bg-sky-400 px-6 text-slate-950 hover:bg-sky-300">
            <a href="/docs"><Code2 aria-hidden="true" />API Documentation</a>
          </Button>
          <Button asChild variant="outline" className="h-11 rounded-full border-white/20 bg-transparent text-white hover:bg-white/10">
            <a href="/redoc">API Reference<ArrowRight aria-hidden="true" /></a>
          </Button>
        </div>
      </div>
      <figure className={cn(glass, "min-w-0 overflow-hidden")}>
        <figcaption className="flex items-center gap-2 border-b border-white/10 px-4 py-3 text-sm text-white/60">
          <Terminal aria-hidden="true" className="size-4" />{t("dev.example")}
        </figcaption>
        <pre className="overflow-x-auto p-5 text-[13px] leading-relaxed text-slate-200" translate="no"><code>
          <span className="text-white/45">$ </span>curl -H <span className="text-emerald-300">"X-API-Key: YOUR_KEY"</span> \{"\n"}
          {"    "}<span className="text-emerald-300">"https://skymate-thfc.onrender.com/v1/current?q=Baku"</span>{"\n\n"}
          {"{\n"}
          {"  "}<span className="text-sky-300">"location"</span>: {"{ "}<span className="text-sky-300">"name"</span>: <span className="text-emerald-300">"Baku"</span>, <span className="text-sky-300">"country"</span>: <span className="text-emerald-300">"AZ"</span>{" },\n"}
          {"  "}<span className="text-sky-300">"observed"</span>: {"{ "}<span className="text-sky-300">"temperature"</span>: 26.0, <span className="text-sky-300">"age_minutes"</span>: 9{" },\n"}
          {"  "}<span className="text-sky-300">"current"</span>: {"{ "}<span className="text-sky-300">"description"</span>: <span className="text-emerald-300">"few clouds"</span>{" },\n"}
          {"  "}<span className="text-sky-300">"meta"</span>: {"{ "}<span className="text-sky-300">"source"</span>: <span className="text-emerald-300">"skymate"</span>{" }\n}"}
        </code></pre>
      </figure>
    </section>
  )
}

const FAQ = ["1", "2", "3", "4", "5", "6"] as const

export function Faq() {
  const { t } = useT()
  return (
    <section id="faq" aria-labelledby="faq-title" className="scroll-mt-24">
      <SectionHead id="faq-title" kicker={t("sec.faq.kicker")} title={t("sec.faq.title")} />
      <Accordion type="single" collapsible className={cn(glass, "mx-auto max-w-3xl px-5 sm:px-7")}>
        {FAQ.map((n) => (
          <AccordionItem key={n} value={n} className="border-white/10">
            <AccordionTrigger className="py-5 text-left text-base text-white hover:no-underline">{t(`faq.q${n}`)}</AccordionTrigger>
            <AccordionContent className="text-pretty text-[15px] leading-relaxed text-white/65">{t(`faq.a${n}`)}</AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </section>
  )
}

export function Cta({ bot }: { bot: string }) {
  const { t } = useT()
  return (
    <section aria-labelledby="cta-title" className="relative overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-sky-700/80 via-blue-900/80 to-indigo-950/80 p-8 sm:p-12">
      <BorderBeam size={160} duration={12} colorFrom="#ffffff" colorTo="#7cc7ff" />
      <div className="flex flex-col items-start justify-between gap-6 md:flex-row md:items-center">
        <div>
          <div className="mb-3 inline-flex rounded-full border border-white/20 bg-white/10 px-3 py-1 text-sm">
            <AnimatedShinyText className="text-white/80">{t("cta.kicker")}</AnimatedShinyText>
          </div>
          <h2 id="cta-title" className="text-balance text-3xl font-semibold text-white">{t("cta.title")}</h2>
          <p className="mt-2 text-white/75">{t("cta.lead")}</p>
        </div>
        <Button asChild className="h-12 rounded-full bg-white px-7 text-base text-slate-900 hover:bg-sky-100">
          <a href={`https://t.me/${bot}`} target="_blank" rel="noopener noreferrer">{t("tg.open")}</a>
        </Button>
      </div>
    </section>
  )
}
