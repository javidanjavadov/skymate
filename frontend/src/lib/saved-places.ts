/**
 * Places the visitor saved, kept in their own browser.
 *
 * One shared list so the star on the weather card and the row of saved places always agree.
 */
import { useSyncExternalStore } from "react"

export type Saved = { name: string; country: string; lat: number; lon: number }

const KEY = "skymate-saved"
const LIMIT = 8

function read(): Saved[] {
  try {
    const list = JSON.parse(localStorage.getItem(KEY) ?? "[]")
    return Array.isArray(list) ? list.slice(0, LIMIT) : []
  } catch {
    return []
  }
}

let places: Saved[] = typeof window === "undefined" ? [] : read()
const listeners = new Set<() => void>()

function write(next: Saved[]) {
  places = next
  try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* storage unavailable */ }
  listeners.forEach((l) => l())
}

/** Two points count as the same place when they are within a few kilometres. */
export const samePlace = (a: Saved, b: Saved) => Math.abs(a.lat - b.lat) < 0.05 && Math.abs(a.lon - b.lon) < 0.05

export const isSaved = (list: Saved[], place: Saved | null) => !!place && list.some((s) => samePlace(s, place))

export function toggleSaved(place: Saved) {
  write(isSaved(places, place) ? places.filter((s) => !samePlace(s, place)) : [place, ...places].slice(0, LIMIT))
}

export function removeSaved(place: Saved) {
  write(places.filter((s) => !samePlace(s, place)))
}

export function useSavedPlaces(): Saved[] {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb) },
    () => places,
    () => places,
  )
}
