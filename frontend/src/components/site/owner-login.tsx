import { useId, useState } from "react"
import { Lock } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

/** Same derivation as skymate_api/security.py admin_prefix(): the console lives under a secret path. */
async function consolePath(token: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`skymate-admin-path:${token}`))
  const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("")
  return `/console-${hex.slice(0, 24)}`
}

/** Owner sign-in. The token never leaves this origin except as the header the console itself uses. */
export function OwnerLogin() {
  const id = useId()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  return (
    <section className="mx-auto mt-10 max-w-md rounded-3xl border border-white/15 bg-slate-950/70 p-6 sm:p-8">
      <div className="flex items-center gap-3">
        <span className="grid size-10 place-items-center rounded-full bg-white/10"><Lock aria-hidden="true" className="size-5" /></span>
        <div>
          <h1 className="text-xl font-semibold text-white">Owner Sign-In</h1>
          <p className="text-sm text-white/60">Admin console for SkyMate.</p>
        </div>
      </div>
      <form
        className="mt-6 space-y-3"
        onSubmit={async (e) => {
          e.preventDefault()
          const token = String(new FormData(e.currentTarget).get("token") ?? "").trim()
          if (!token) return
          setBusy(true)
          setError("")
          try {
            const path = await consolePath(token)
            const r = await fetch(`${path}/api/overview`, { headers: { "X-Admin-Token": token }, cache: "no-store" })
            if (!r.ok || !r.headers.get("content-type")?.includes("json")) throw new Error()
            sessionStorage.setItem("sm_admin", token)
            location.assign(`${path}/`)
          } catch {
            setError("Wrong token. After 5 failed attempts, sign-in is locked for 15 minutes.")
            setBusy(false)
          }
        }}
      >
        <label htmlFor={id} className="text-sm text-white/80">Admin token</label>
        <Input id={id} name="token" type="password" autoComplete="current-password" required spellCheck={false}
          className="h-11 border-white/15 bg-white/5 text-white" />
        <p role="alert" aria-live="polite" className={error ? "text-sm text-red-300" : "sr-only"}>{error}</p>
        <Button type="submit" disabled={busy} className="h-11 w-full rounded-full bg-white text-slate-900 hover:bg-sky-100">
          {busy ? "Checking…" : "Sign In"}
        </Button>
      </form>
    </section>
  )
}
