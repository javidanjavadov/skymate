import type { ReactNode } from "react"

import { useT } from "@/lib/i18n"

function Page({ title, children }: { title: string; children: ReactNode }) {
  const { t, language } = useT()
  return (
    <article className="mx-auto max-w-3xl rounded-3xl border border-white/10 bg-slate-950/80 p-6 sm:p-10
      [&_h2]:mt-10 [&_h2]:scroll-mt-24 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-white
      [&_li]:mt-2 [&_p]:mt-3 [&_p]:text-pretty [&_p]:leading-relaxed [&_p]:text-white/75
      [&_ul]:mt-3 [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-5 [&_ul]:text-white/75 [&_a]:text-sky-300 [&_a]:underline-offset-4 [&_a:hover]:underline">
      <h1 className="text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h1>
      <p className="!mt-2 text-sm !text-white/50">{t("legal.updated", { date: t("legal.date") })}</p>
      {language !== "en" && <p className="!mt-1 text-sm !text-white/40">{t("legal.authoritative")}</p>}
      {children}
    </article>
  )
}

const BOT = <a href="https://t.me/skymatee_bot" target="_blank" rel="noopener noreferrer">@skymatee_bot</a>

/** Splits a sentence that mentions {bot} so the bot name stays a link. */
function WithBot({ text }: { text: string }) {
  const [before, after = ""] = text.split("{bot}")
  return <>{before}{BOT}{after}</>
}

export function Terms() {
  const { t } = useT()
  const list = (keys: string[]) => (
    <ul>{keys.map((k) => <li key={k}>{t(k as Parameters<typeof t>[0])}</li>)}</ul>
  )
  return (
    <Page title={t("terms.title")}>
      <p><WithBot text={t("terms.intro")} /></p>
      <h2 id="service">{t("terms.1.title")}</h2>
      <p>{t("terms.1.body")}</p>
      <h2 id="guidance">{t("terms.2.title")}</h2>
      <p>{t("terms.2.body")}</p>
      <h2 id="accounts">{t("terms.3.title")}</h2>
      {list(["terms.3.1", "terms.3.2"])}
      <h2 id="premium">{t("terms.4.title")}</h2>
      {list(["terms.4.1", "terms.4.2", "terms.4.3", "terms.4.4"])}
      <h2 id="api">{t("terms.5.title")}</h2>
      {list(["terms.5.1", "terms.5.2", "terms.5.3"])}
      <h2 id="use">{t("terms.6.title")}</h2>
      <p>{t("terms.6.intro")}</p>
      {list(["terms.6.1", "terms.6.2", "terms.6.3", "terms.6.4"])}
      <p>{t("terms.6.end")}</p>
      <h2 id="availability">{t("terms.7.title")}</h2>
      <p>{t("terms.7.body")}</p>
      <h2 id="third-party">{t("terms.8.title")}</h2>
      <p>{t("terms.8.body")}</p>
      <h2 id="liability">{t("terms.9.title")}</h2>
      <p>{t("terms.9.body")}</p>
      <h2 id="changes">{t("terms.10.title")}</h2>
      <p>{t("terms.10.body")}</p>
      <h2 id="contact">{t("terms.11.title")}</h2>
      <p><WithBot text={t("terms.11.body")} /></p>
    </Page>
  )
}

export function Privacy() {
  const { t } = useT()
  const list = (keys: string[]) => (
    <ul>{keys.map((k) => <li key={k}>{t(k as Parameters<typeof t>[0])}</li>)}</ul>
  )
  return (
    <Page title={t("privacy.title")}>
      <p className="rounded-2xl bg-sky-400/10 p-4 !text-white/85">{t("privacy.short")}</p>
      <h2 id="collect">{t("privacy.1.title")}</h2>
      <p><strong className="text-white">{t("privacy.bot")}</strong></p>
      {list(["privacy.bot.1", "privacy.bot.2", "privacy.bot.3", "privacy.bot.4"])}
      <p><strong className="text-white">{t("privacy.api")}</strong></p>
      {list(["privacy.api.1", "privacy.api.2"])}
      <p><strong className="text-white">{t("privacy.web")}</strong></p>
      {list(["privacy.web.1", "privacy.web.2", "privacy.web.3"])}
      <h2 id="use">{t("privacy.2.title")}</h2>
      {list(["privacy.2.1", "privacy.2.2", "privacy.2.3"])}
      <p>{t("privacy.2.end")}</p>
      <h2 id="processors">{t("privacy.3.title")}</h2>
      {list(["privacy.3.1", "privacy.3.2", "privacy.3.3"])}
      <h2 id="retention">{t("privacy.4.title")}</h2>
      {list(["privacy.4.1", "privacy.4.2", "privacy.4.3"])}
      <h2 id="rights">{t("privacy.5.title")}</h2>
      {list(["privacy.5.1", "privacy.5.2"])}
      <h2 id="security">{t("privacy.6.title")}</h2>
      <p>{t("privacy.6.body")}</p>
      <h2 id="children">{t("privacy.7.title")}</h2>
      <p>{t("privacy.7.body")}</p>
      <h2 id="changes">{t("privacy.8.title")}</h2>
      <p>{t("privacy.8.body")}</p>
      <h2 id="contact">{t("privacy.9.title")}</h2>
      <p><WithBot text={t("privacy.9.body")} /></p>
    </Page>
  )
}
