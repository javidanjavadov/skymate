import type { ReactNode } from "react"

const UPDATED = "19 September 2026"

function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-3xl rounded-3xl border border-white/10 bg-slate-950/80 p-6 sm:p-10
      [&_h2]:mt-10 [&_h2]:scroll-mt-24 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-white
      [&_li]:mt-2 [&_p]:mt-3 [&_p]:text-pretty [&_p]:leading-relaxed [&_p]:text-white/75
      [&_ul]:mt-3 [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-5 [&_ul]:text-white/75 [&_a]:text-sky-300 [&_a]:underline-offset-4 [&_a:hover]:underline">
      <h1 className="text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h1>
      <p className="!mt-2 text-sm !text-white/50">Last updated: {UPDATED}</p>
      {children}
    </article>
  )
}

const BOT = <a href="https://t.me/skymatee_bot" target="_blank" rel="noopener noreferrer">@skymatee_bot</a>

export function Terms() {
  return (
    <Page title="Terms of Service">
      <p>These terms govern your use of SkyMate: the Telegram bot {BOT}, the website and the
        SkyMate Weather API (together, the “Service”). By using the Service you agree to these terms.</p>
      <h2 id="service">1. The Service</h2>
      <p>SkyMate provides weather information: measurements from third-party weather stations, forecasts derived from global
        weather models, warnings, UV index, air quality, maps and related data. Features may change as the Service evolves.</p>
      <h2 id="guidance">2. Weather Information Is Provided for General Guidance</h2>
      <p>Measurements can be delayed or incorrect, and forecasts are estimates that can be wrong. The Service is <strong>not</strong> a
        substitute for official warnings from your national weather service or civil protection authorities. Do not rely on SkyMate
        where an error could cause injury, loss of life or significant financial loss, including aviation, maritime navigation or emergency response.</p>
      <h2 id="accounts">3. Accounts and Keys</h2>
      <ul>
        <li>Your Telegram account identifies you in the bot. You are responsible for activity under it.</li>
        <li>API keys are personal to you or your organisation. Keep them secret. Keys that are shared, leaked or misused may be revoked.</li>
      </ul>
      <h2 id="premium">4. Premium Subscriptions</h2>
      <ul>
        <li>Premium is purchased inside Telegram with Telegram Stars and renews every 30 days until cancelled.</li>
        <li>Cancel anytime in Telegram: Settings → My Stars. Premium stays active until the end of the paid period.</li>
        <li>Payments are processed by Telegram; SkyMate never receives your card details.</li>
        <li>If a payment was made in error or the Service didn’t work as described, send /paysupport in the bot. Refunds are handled case by case and issued through Telegram.</li>
      </ul>
      <h2 id="api">5. Weather API Plans</h2>
      <ul>
        <li>API use is limited by the quotas of your plan. Requests beyond the limits are rejected.</li>
        <li>Paid plans are billed as agreed when your key is issued. Plans, prices and limits may change with notice.</li>
        <li>Display the data attribution included in API responses (NOAA, ECMWF, GeoNames) wherever you show the data to others.</li>
      </ul>
      <h2 id="use">6. Acceptable Use</h2>
      <p>You must not:</p>
      <ul>
        <li>access parts of the Service you aren’t authorised to use, or test its security without written permission;</li>
        <li>overload the Service, circumvent rate limits, or scrape it outside the API;</li>
        <li>resell raw data from the Service without a plan that permits it;</li>
        <li>use the Service for anything unlawful.</li>
      </ul>
      <p>Access that breaks these rules may be suspended or terminated.</p>
      <h2 id="availability">7. Availability</h2>
      <p>SkyMate works to keep the Service available but doesn’t guarantee uninterrupted operation. When data sources are delayed or
        unavailable, SkyMate serves stored data and labels its age.</p>
      <h2 id="third-party">8. Third-Party Data</h2>
      <p>The Service uses data from NOAA (public domain), ECMWF open data (CC BY 4.0), GeoNames (CC BY 4.0), airport and national weather
        station networks, and air-quality providers. These providers are not responsible for SkyMate.</p>
      <h2 id="liability">9. Liability</h2>
      <p>To the extent permitted by law, the Service is provided “as is” without warranties, and SkyMate is not liable for indirect or
        consequential damages arising from its use. Total liability for any claim is limited to the amount you paid for the Service in the
        three months before the claim.</p>
      <h2 id="changes">10. Changes</h2>
      <p>These terms may be updated. Material changes will be announced in the bot or on this page. Continued use after a change means you accept the updated terms.</p>
      <h2 id="contact">11. Contact</h2>
      <p>Questions about these terms or payments: send /paysupport to {BOT}.</p>
    </Page>
  )
}

export function Privacy() {
  return (
    <Page title="Privacy Policy">
      <p className="rounded-2xl bg-sky-400/10 p-4 !text-white/85">Short version: SkyMate collects only what’s needed to run the service,
        never sells your data, and you can delete your data anytime by sending /deletemydata to the bot.</p>
      <h2 id="collect">1. What Is Collected</h2>
      <p><strong className="text-white">Telegram bot</strong></p>
      <ul>
        <li>Your Telegram user ID, username, first and last name and language, as provided by Telegram;</li>
        <li>your settings (units), favorite cities, daily-report city, and when you last used the bot;</li>
        <li>locations you choose to share, used only to answer that request and not stored;</li>
        <li>Premium payment records received from Telegram: payment ID, amount in Stars and dates. Card or bank details are never visible to SkyMate.</li>
      </ul>
      <p><strong className="text-white">Weather API</strong></p>
      <ul>
        <li>A hashed form of your key, your plan, and request counts per day and endpoint;</li>
        <li>technical request logs (time, path, IP address), kept for security and troubleshooting.</li>
      </ul>
      <p><strong className="text-white">Website</strong></p>
      <ul>
        <li>Standard request logs. The website uses no cookies, analytics or trackers.</li>
        <li>If you allow your location, your coordinates are used to fetch the weather and are not stored with anything that
          identifies you. To name your neighbourhood, SkyMate sends the position rounded to about 100&nbsp;m to OpenStreetMap
          (Nominatim) the first time anyone views that area, and keeps only the area’s name.</li>
        <li>Your last viewed place and its weather are saved in your own browser, not on SkyMate’s servers, so the page opens
          instantly next time. Clearing your browser’s site data removes them.</li>
      </ul>
      <h2 id="use">2. How It’s Used</h2>
      <ul>
        <li>To provide the Service: answering requests, sending the reports and warnings you asked for, applying your plan;</li>
        <li>to process Premium subscriptions and refunds;</li>
        <li>to protect the Service against abuse and to fix problems.</li>
      </ul>
      <p>Personal data is never sold or used for advertising.</p>
      <h2 id="processors">3. Who Processes It</h2>
      <ul>
        <li><strong className="text-white">Telegram</strong>: delivers messages and processes Stars payments;</li>
        <li><strong className="text-white">Render</strong>: hosts the SkyMate servers and database (EU region, Frankfurt);</li>
        <li>weather data providers receive only coordinates or place names needed for a forecast, never your identity.</li>
      </ul>
      <h2 id="retention">4. How Long It’s Kept</h2>
      <ul>
        <li>Account data: until you delete it or stop using the Service;</li>
        <li>payment records: as long as required for accounting and to handle refunds;</li>
        <li>request logs: a limited period for security and troubleshooting.</li>
      </ul>
      <h2 id="rights">5. Your Rights</h2>
      <ul>
        <li><strong className="text-white">Delete</strong>: send /deletemydata to the bot. This removes your settings, favorites, reports,
          keys and profile. Payment records are kept where the law requires it.</li>
        <li><strong className="text-white">Access or correct</strong>: contact support through /paysupport in the bot.</li>
      </ul>
      <h2 id="security">6. Security</h2>
      <p>Traffic is encrypted with HTTPS. Keys are stored only as secure hashes. Access to the owner console is restricted and logged.</p>
      <h2 id="children">7. Children</h2>
      <p>The Service is not directed at children under 13, and their data is not knowingly collected.</p>
      <h2 id="changes">8. Changes</h2>
      <p>Updates are posted on this page, and material changes are announced in the bot.</p>
      <h2 id="contact">9. Contact</h2>
      <p>Send /paysupport to {BOT}.</p>
    </Page>
  )
}
