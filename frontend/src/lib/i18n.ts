/**
 * Three languages for the weather app: English, Azerbaijani and Russian.
 *
 * The visitor's choice is remembered; otherwise the phone's own language decides. Only the weather part of the page
 * is translated so far — the sections further down stay in English until they are translated too.
 */
import { useSyncExternalStore } from "react"

export const LANGUAGES = [
  { code: "en", label: "English", short: "EN" },
  { code: "az", label: "Azərbaycan", short: "AZ" },
  { code: "ru", label: "Русский", short: "RU" },
] as const

export type Language = (typeof LANGUAGES)[number]["code"]

const STORE_KEY = "skymate-language"

function detect(): Language {
  try {
    const saved = localStorage.getItem(STORE_KEY) as Language | null
    if (saved && LANGUAGES.some((l) => l.code === saved)) return saved
  } catch { /* storage unavailable */ }
  const wanted = (typeof navigator !== "undefined" ? navigator.languages ?? [navigator.language] : []).map((l) => l.slice(0, 2))
  return (wanted.find((l) => LANGUAGES.some((x) => x.code === l)) as Language) ?? "en"
}

let current: Language = typeof window === "undefined" ? "en" : detect()
const listeners = new Set<() => void>()

export function setLanguage(code: Language) {
  current = code
  try { localStorage.setItem(STORE_KEY, code) } catch { /* storage unavailable */ }
  document.documentElement.lang = code
  listeners.forEach((l) => l())
}

/** The current language outside React (formatting helpers, error messages). */
export const getLanguage = () => current

export function useLanguage(): Language {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb) },
    () => current,
    () => "en" as Language,
  )
}

/** Locale for dates and numbers; Azerbaijani falls back to az-Latn. */
export const localeOf = (code: Language) => (code === "az" ? "az-Latn-AZ" : code === "ru" ? "ru-RU" : "en")

type Dict = Record<string, string>

const az: Dict = {
  "search.label": "Şəhər axtar",
  "search.placeholder": "Şəhər axtarın, məsələn Bakı…",
  "search.button": "Axtar",
  "search.loading": "Yüklənir…",
  "search.locate": "Məni tap",
  "search.none": "Uyğun yer tapılmadı. Yazılışı yoxlayın.",
  "search.list": "Uyğun yerlər",
  "saved.save": "Bu yeri yadda saxla",
  "saved.saved": "Saxlanıldı",
  "now.back": "İndiki vaxta qayıt",
  "now.badge": "İndi",
  "now.measured": "Ölçülüb {age}",
  "now.model": "Model təxmini",
  "now.updating": "Yenilənir · {age} məlumat",
  "now.forecast": "Proqnoz · ",
  "now.station": "Temperatur {station} stansiyasında ölçülüb, {km} km uzaqda",
  "tile.feels": "Hiss olunur",
  "tile.precip": "Yağıntı",
  "tile.visibility": "Görünüş",
  "tile.humidity": "Rütubət",
  "card.hourly": "Saatlıq proqnoz",
  "card.daily": "{n} günlük proqnoz",
  "card.uv": "UV indeksi",
  "card.uvPeak": "UV indeksi · pik",
  "card.wind": "Külək",
  "card.windMax": "Maksimum külək",
  "card.gusts": "Küləyin gücü",
  "card.sun": "Günəş",
  "card.trust": "Məlumat haradandır",
  "tab.hourly": "Saatlıq",
  "tab.days": "{n} gün",
  "sun.sunrise": "Gün doğuşu",
  "sun.sunset": "Gün batışı",
  "sun.daylight": "Gündüz",
  "trust.measuredAt": "Ölçmə yeri",
  "trust.noStation": "Yaxınlıqda stansiya yoxdur",
  "trust.model": "Proqnoz modeli",
  "trust.compare": "Model və stansiya",
  "error.offline": "SkyMate-ə çıxış yoxdur. İnternetinizi yoxlayıb yenidən cəhd edin.",
  "error.slow": "SkyMate cavab vermir. Bir dəqiqədən sonra yenidən cəhd edin.",
  "error.generic": "Nəsə səhv getdi. Bir azdan yenidən cəhd edin.",
  "error.retry": "Yenidən cəhd et",
  "error.locationBlocked": "Məkana icazə verilmədi. Brauzerdən icazə verin və ya şəhəri axtarın.",
  "error.noGeolocation": "Brauzeriniz məkanı paylaşa bilmir. Şəhəri axtarın.",
  "units.metric": "°C",
  "units.imperial": "°F",
  "nav.language": "Dil",
}

const ru: Dict = {
  "search.label": "Поиск города",
  "search.placeholder": "Найдите город, например Баку…",
  "search.button": "Поиск",
  "search.loading": "Загрузка…",
  "search.locate": "Моё местоположение",
  "search.none": "Ничего не найдено. Проверьте написание.",
  "search.list": "Подходящие места",
  "saved.save": "Сохранить место",
  "saved.saved": "Сохранено",
  "now.back": "Вернуться к текущему",
  "now.badge": "Сейчас",
  "now.measured": "Измерено {age}",
  "now.model": "Оценка модели",
  "now.updating": "Обновляется · данные {age}",
  "now.forecast": "Прогноз · ",
  "now.station": "Температура измерена на станции {station}, в {km} км",
  "tile.feels": "Ощущается",
  "tile.precip": "Осадки",
  "tile.visibility": "Видимость",
  "tile.humidity": "Влажность",
  "card.hourly": "Почасовой прогноз",
  "card.daily": "Прогноз на {n} дней",
  "card.uv": "УФ-индекс",
  "card.uvPeak": "УФ-индекс · пик",
  "card.wind": "Ветер",
  "card.windMax": "Максимальный ветер",
  "card.gusts": "Порывы",
  "card.sun": "Солнце",
  "card.trust": "Откуда эти данные",
  "tab.hourly": "По часам",
  "tab.days": "{n} дней",
  "sun.sunrise": "Восход",
  "sun.sunset": "Закат",
  "sun.daylight": "Световой день",
  "trust.measuredAt": "Место измерения",
  "trust.noStation": "Рядом нет станции",
  "trust.model": "Модель прогноза",
  "trust.compare": "Модель и станция",
  "error.offline": "Нет связи со SkyMate. Проверьте интернет и попробуйте снова.",
  "error.slow": "SkyMate отвечает слишком долго. Попробуйте через минуту.",
  "error.generic": "Что-то пошло не так. Попробуйте позже.",
  "error.retry": "Повторить",
  "error.locationBlocked": "Доступ к местоположению закрыт. Разрешите его или найдите город.",
  "error.noGeolocation": "Браузер не может передать местоположение. Найдите город.",
  "units.metric": "°C",
  "units.imperial": "°F",
  "nav.language": "Язык",
}

const en: Dict = {
  "search.label": "Search for a city",
  "search.placeholder": "Search a city, e.g. Hanoi…",
  "search.button": "Search",
  "search.loading": "Loading…",
  "search.locate": "Use my location",
  "search.none": "No matching places. Check the spelling.",
  "search.list": "Matching places",
  "saved.save": "Save this place",
  "saved.saved": "Saved",
  "now.back": "Back to Now",
  "now.badge": "Now",
  "now.measured": "Measured {age}",
  "now.model": "Model estimate",
  "now.updating": "Updating · from {age}",
  "now.forecast": "Forecast · ",
  "now.station": "Temperature measured at {station}, {km} km away",
  "tile.feels": "Feels like",
  "tile.precip": "Precipitation",
  "tile.visibility": "Visibility",
  "tile.humidity": "Humidity",
  "card.hourly": "Hourly Forecast",
  "card.daily": "{n}-Day Forecast",
  "card.uv": "UV Index",
  "card.uvPeak": "UV Index · Peak",
  "card.wind": "Wind",
  "card.windMax": "Max Wind",
  "card.gusts": "Gusts",
  "card.sun": "Sun",
  "card.trust": "Where This Comes From",
  "tab.hourly": "Hourly",
  "tab.days": "{n} Days",
  "sun.sunrise": "Sunrise",
  "sun.sunset": "Sunset",
  "sun.daylight": "Daylight",
  "trust.measuredAt": "Measured at",
  "trust.noStation": "No station nearby",
  "trust.model": "Forecast model",
  "trust.compare": "Model vs station",
  "error.offline": "Can’t reach SkyMate. Check your connection and try again.",
  "error.slow": "SkyMate is taking too long to respond. It may be starting up; try again in a minute.",
  "error.generic": "Something went wrong. Try again in a moment.",
  "error.retry": "Try Again",
  "error.locationBlocked": "Location access was blocked. Allow it in your browser, or search for your city.",
  "error.noGeolocation": "Your browser can’t share your location. Search for your city instead.",
  "units.metric": "°C",
  "units.imperial": "°F",
  "nav.language": "Language",
}

const DICTS: Record<Language, Dict> = { en, az, ru }

/** Translated text for the current language; {placeholders} are filled from `values`. */
export function translate(code: Language, key: keyof typeof en, values?: Record<string, string | number>) {
  const text = DICTS[code][key] ?? en[key] ?? String(key)
  return values ? text.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? "")) : text
}

/** The translator for the current language, e.g. t("card.wind"). */
export function useT() {
  const code = useLanguage()
  const t = (key: keyof typeof en, values?: Record<string, string | number>) => translate(code, key, values)
  return { t, language: code, locale: localeOf(code) }
}
