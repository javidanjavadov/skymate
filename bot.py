import asyncio
import io
import logging
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytz
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent,
    KeyboardButton, LabeledPrice, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update,
)
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
    ApplicationHandlerStop, InlineQueryHandler, MessageHandler, PreCheckoutQueryHandler, TypeHandler, filters,
)

from skymate_api import store
from skymate_api.config import load_env
from skymate_client import SkyMate, SkyMateAdmin, SkyMateError, admin_prefix

load_env()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_ADMIN_ID = int(os.environ.get("BOT_ADMIN_ID", "0") or 0)
PREMIUM_STARS = int(os.environ.get("PREMIUM_STARS", "150"))
SUPPORT_CONTACT = os.environ.get("SUPPORT_CONTACT", "")
APP_DOWNLOAD_URL = os.environ.get("APP_DOWNLOAD_URL", "")
PUBLIC_API_URL = os.environ.get("PUBLIC_API_URL", "")
DEFAULT_UNITS = 'metric'
FREE_FAVORITES = 3
MAX_TEXT = 100
USER_RATE_LIMIT = 30  # updates per minute per user
FREE_HISTORY_DAYS = 7
api = SkyMate()
admin_api = SkyMateAdmin()

PREMIUM_BENEFITS = (
    "⭐ *SkyMate Premium*\n\n"
    "• 🚨 Instant severe-weather warnings for your city\n"
    "• 📅 10-day forecasts (/week)\n"
    "• 📈 Up to a full year of measured history per chart, archive back to 1932\n"
    "• ❤️ Unlimited favorite cities (free: 3)\n"
    "• 💻 Premium in the SkyMate desktop app (/app)\n"
)

WEATHER_EMOJIS = {
    'Clear': '☀️', 'Clouds': '☁️', 'Rain': '🌧️', 'Drizzle': '🌦️', 'Thunderstorm': '⛈️',
    'Snow': '❄️', 'Mist': '🌫️', 'Fog': '🌫️',
}
NIGHT_EMOJIS = {'Clear': '🌙'}
EU_AQI = [(20, "Good 😊"), (40, "Fair 🙂"), (60, "Moderate 😐"), (80, "Poor 😷"), (100, "Very poor 🤢"),
          (10_000, "Extremely poor ☠️")]
UV_LABELS = {"low": "Low", "moderate": "Moderate 🌤️", "high": "High ⛱️", "very_high": "Very high 🚫",
             "extreme": "Extreme ☢️"}
SEVERITY_ICON = {"severe": "🔴", "moderate": "🟠", "minor": "🟡"}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

STATE_ADD_FAVORITE, STATE_REMOVE_FAVORITE = range(2)


# ─── Database (per-user settings) ─────────────────────────────────────────────

def init_db():
    store.init("bot")
    with store.tx("bot") as conn:
        # Users known from earlier activity, before the users table existed.
        conn.execute("INSERT INTO users(user_id, actions) SELECT user_id, 0 FROM (SELECT user_id FROM user_settings "
                     "UNION SELECT user_id FROM user_favorites UNION SELECT user_id FROM user_subscriptions) AS known "
                     "WHERE 1=1 ON CONFLICT DO NOTHING")

def premium_until(user_id: int) -> datetime | None:
    with store.tx("bot") as conn:
        row = conn.execute('SELECT until FROM premium WHERE user_id=?', (user_id,)).fetchone()
    return datetime.fromtimestamp(row[0], tz=timezone.utc) if row and row[0] else None

def is_premium(user_id: int) -> bool:
    until = premium_until(user_id)
    return bool(until and until > datetime.now(timezone.utc))

def grant_premium(user_id: int, until: datetime, charge_id: str, stars: int, recurring: bool):
    with store.tx("bot") as conn:
        conn.execute('INSERT INTO premium(user_id, until, charge_id, recurring, updated_at) VALUES (?,?,?,?,?) '
                     'ON CONFLICT(user_id) DO UPDATE SET until=excluded.until, charge_id=excluded.charge_id, '
                     'recurring=excluded.recurring, updated_at=excluded.updated_at',
                     (user_id, int(until.timestamp()), charge_id, 1 if recurring else 0, store.now()))
        conn.execute('INSERT INTO payments(charge_id, user_id, stars, until, created_at) VALUES (?,?,?,?,?) '
                     'ON CONFLICT DO NOTHING', (charge_id, user_id, stars, int(until.timestamp()), store.now()))

def has_app_key(user_id: int) -> bool:
    with store.tx("bot") as conn:
        return conn.execute('SELECT 1 FROM app_keys WHERE user_id=?', (user_id,)).fetchone() is not None

def get_user_units(user_id: int) -> str:
    with store.tx("bot") as conn:
        row = conn.execute('SELECT units FROM user_settings WHERE user_id=?', (user_id,)).fetchone()
    return row[0] if row else DEFAULT_UNITS

def set_user_units(user_id: int, units: str):
    with store.tx("bot") as conn:
        conn.execute('INSERT INTO user_settings(user_id, units) VALUES (?,?) '
                     'ON CONFLICT(user_id) DO UPDATE SET units=excluded.units', (user_id, units))

def get_user_favorites(user_id: int) -> list:
    with store.tx("bot") as conn:
        rows = conn.execute('SELECT city FROM user_favorites WHERE user_id=? ORDER BY city', (user_id,)).fetchall()
    return [r[0] for r in rows]

def add_user_favorite(user_id: int, city: str):
    with store.tx("bot") as conn:
        conn.execute('INSERT INTO user_favorites(user_id, city) VALUES (?,?) ON CONFLICT DO NOTHING', (user_id, city))

def remove_user_favorite(user_id: int, city: str):
    with store.tx("bot") as conn:
        conn.execute('DELETE FROM user_favorites WHERE user_id=? AND city=?', (user_id, city))

def get_subscription(user_id: int):
    with store.tx("bot") as conn:
        row = conn.execute('SELECT chat_id, city, units FROM user_subscriptions WHERE user_id=?', (user_id,)).fetchone()
    return {'chat_id': row[0], 'city': row[1], 'units': row[2]} if row else None

def get_all_subscriptions():
    with store.tx("bot") as conn:
        return conn.execute('SELECT user_id, chat_id, city, units FROM user_subscriptions').fetchall()

def save_subscription(user_id: int, chat_id: int, city: str, units: str):
    with store.tx("bot") as conn:
        conn.execute('INSERT INTO user_subscriptions(user_id, chat_id, city, units) VALUES (?,?,?,?) '
                     'ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id, city=excluded.city, '
                     'units=excluded.units', (user_id, chat_id, city, units))

def delete_subscription(user_id: int):
    with store.tx("bot") as conn:
        conn.execute('DELETE FROM user_subscriptions WHERE user_id=?', (user_id,))


# ─── API access ───────────────────────────────────────────────────────────────

async def call(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def where(city=None, lat=None, lon=None) -> dict:
    return {"q": city} if city else {"lat": lat, "lon": lon}


def error_text(e: SkyMateError, what: str = "") -> str:
    if e.status == 404:
        return f"❌ {what or 'Location'} not found."
    if e.status == 0:
        return "⚠️ Weather service is restarting. Please try again in a minute."
    return f"❌ {e.message}"


def md(text) -> str:
    """Escape user or third-party text for Telegram Markdown (legacy mode)."""
    return re.sub(r"([_*`\[])", r"\\\1", str(text))


def city_arg(context) -> str | None:
    value = ' '.join(context.args).strip() if context.args else None
    return value[:MAX_TEXT] if value else None


_user_hits: dict[int, deque] = defaultdict(deque)
_user_warned: dict[int, float] = {}


async def rate_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Drops updates from users sending more than USER_RATE_LIMIT per minute."""
    u = update.effective_user
    if not u:
        return
    now = time.monotonic()
    q = _user_hits[u.id]
    while q and now - q[0] > 60:
        q.popleft()
    q.append(now)
    if len(q) > USER_RATE_LIMIT:
        if now - _user_warned.get(u.id, 0) > 60 and update.effective_message:
            _user_warned[u.id] = now
            await update.effective_message.reply_text("⏳ Too many requests. Please wait a minute.")
        raise ApplicationHandlerStop


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner only: sends the private admin panel link. Everyone else gets no reply."""
    if update.effective_user.id != BOT_ADMIN_ID or not BOT_ADMIN_ID:
        return
    token = os.environ.get("SKYMATE_ADMIN_TOKEN", "")
    if not token:
        await update.message.reply_text("Admin panel is not configured on this server.")
        return
    base = (PUBLIC_API_URL or api.base).rstrip("/")
    await update.message.reply_text(
        f"🔐 Admin panel:\n{base}{admin_prefix(token)}/\n\n"
        "Sign in with SKYMATE_ADMIN_TOKEN. Keep this link private; it is only sent to you.",
        disable_web_page_preview=True)


# ─── Formatting ───────────────────────────────────────────────────────────────

def _local(iso: str, loc: dict) -> datetime:
    t = datetime.fromisoformat(iso)
    tz = pytz.timezone(loc.get("timezone") or "UTC")
    return t.astimezone(tz)

def _num(v, digits=0):
    if v is None:
        return "N/A"
    return f"{v:.{digits}f}" if digits else f"{round(v)}"

def _compass(deg):
    return "" if deg is None else COMPASS[int((deg + 22.5) // 45) % 8]

def _emoji(state: dict) -> str:
    if not state.get("is_day", True) and state.get("condition") in NIGHT_EMOJIS:
        return NIGHT_EMOJIS[state["condition"]]
    return WEATHER_EMOJIS.get(state.get("condition"), '🌡')

def _place_plain(loc: dict) -> str:
    return f"{loc['name']}, {loc['country']}" if loc.get("country") else loc["name"]

def _place(loc: dict) -> str:
    return md(f"{loc['name']}, {loc['country']}" if loc.get("country") else loc["name"])

def _freshness(meta: dict) -> str:
    if meta.get("stale"):
        return f"\n\n⚠️ _Offline mode: forecast issued {round(meta['data_age_hours'])} h ago_"
    return ""

def _age(minutes: int) -> str:
    return f"{minutes} min ago" if minutes < 90 else f"{round(minutes / 60)} h ago"

def format_measured(o: dict, u: dict) -> str:
    st = o["station"]
    t, s = u["temperature"], u["speed"]
    parts = [f"🌡 *{_num(o['temperature'], 1)}{t}*"]
    if o.get("humidity") is not None:
        parts.append(f"💧 {_num(o['humidity'])}%")
    if o.get("wind_speed") is not None:
        parts.append(f"💨 {_num(o['wind_speed'], 1)} {s} {_compass(o.get('wind_direction'))}".rstrip())
    if o.get("pressure") is not None:
        parts.append(f"🔵 {_num(o['pressure'])} hPa")
    wx = f"\n   Weather: {o['weather']}" if o.get("weather") else ""
    return (f"📡 *Measured* at {md(st['name'])} ({st['distance_km']} km away, {_age(o['age_minutes'])})\n"
            f"   {'  '.join(parts)}{wx}")

def format_current(d: dict) -> str:
    loc, c, u = d["location"], d["current"], d["units"]
    obs = d.get("observed")
    if c is None:
        return f"📍 *{_place(loc)}*\n\n" + format_measured(obs, u)
    t, s = u["temperature"], u["speed"]
    vis = c.get("visibility")
    vis_txt = (f"{vis / 1000:.0f} km" if u["visibility"] == "m" else f"{vis:.1f} mi") if vis is not None else None
    gust = f" (gusts {_num(c['wind_gust'])})" if c.get("wind_gust") else ""
    lines = [
        f"{_emoji(c)} *{_place(loc)}*",
        f"_{c['description'].capitalize()}_\n",
        f"🌡 Temp: *{_num(c['temperature'])}{t}*",
        f"🤔 Feels like: {_num(c['feels_like'])}{t}",
        f"💧 Humidity: {_num(c['humidity'])}%",
        f"💨 Wind: {_num(c['wind_speed'], 1)} {s} {_compass(c.get('wind_direction'))}{gust}",
        f"🔵 Pressure: {_num(c['pressure'])} hPa",
        f"👁 Visibility: {vis_txt}" if vis_txt else "",
        f"☀️ UV index: {c['uv_index']}",
    ]
    sun = d.get("sun", {})
    if sun.get("sunrise") and sun.get("sunset"):
        lines.append(f"🌅 Sunrise: {_local(sun['sunrise'], loc):%H:%M}  🌇 Sunset: {_local(sun['sunset'], loc):%H:%M}")
    if obs:
        m = " _(measured)_"
        if obs.get("temperature") is not None:
            lines[2] = f"🌡 Temp: *{_num(obs['temperature'])}{t}*{m}"
        if obs.get("humidity") is not None:
            lines[4] = f"💧 Humidity: {_num(obs['humidity'])}%{m}"
        if obs.get("wind_speed") is not None:
            ogust = f" (gusts {_num(obs['wind_gust'])})" if obs.get("wind_gust") else ""
            lines[5] = f"💨 Wind: {_num(obs['wind_speed'], 1)} {s} {_compass(obs.get('wind_direction'))}{ogust}{m}"
        if obs.get("pressure") is not None:
            lines[6] = f"🔵 Pressure: {_num(obs['pressure'])} hPa{m}"
        st = obs["station"]
        lines.append(f"\n📡 Measured at *{md(st['name'])}* ({st['distance_km']} km, {_age(obs['age_minutes'])}). "
                     "Other values are estimates.")
    else:
        lines.append("\n_No weather station nearby: values are model estimates._")
    return "\n".join(l for l in lines if l) + _freshness(d["meta"])

def format_daily(d: dict) -> str:
    loc, u = d["location"], d["units"]
    msg = f"📅 *{len(d['daily'])}-Day Forecast — {_place(loc)}*\n\n"
    for day in d["daily"]:
        date = datetime.fromisoformat(day["date"])
        emoji = WEATHER_EMOJIS.get(day["condition"], '🌡')
        rain = day.get("precipitation_sum") or 0
        rain_txt = f"  💧 {rain:.1f} {u['precipitation']}" if rain >= 0.1 else ""
        msg += (f"*{date:%A}* ({date:%d %b}): {emoji} {day['description'].capitalize()}\n"
                f"  ↓ {_num(day['temp_min'])}{u['temperature']}  ↑ {_num(day['temp_max'])}{u['temperature']}{rain_txt}\n\n")
    return msg + _freshness(d["meta"]).strip()

def format_hourly(d: dict) -> str:
    loc, u = d["location"], d["units"]
    msg = f"⏳ *Next 24 Hours — {_place(loc)}*\n\n"
    for h in d["hourly"][:9]:
        msg += (f"{_local(h['time'], loc):%H:%M} {_emoji(h)} {h['description'].capitalize()} — "
                f"{_num(h['temperature'])}{u['temperature']}\n")
    return msg + _freshness(d["meta"])

def format_uv(d: dict) -> str:
    return (f"☀️ *UV Index — {_place(d['location'])}*\n\n"
            f"Now: *{d['uv_index']}* ({UV_LABELS[d['category']]})\n"
            f"Today's max: {d['uv_max_today']}")

def format_aqi(d: dict) -> str:
    aq = d["air_quality"]
    comp = aq["components"]
    if aq.get("european_aqi") is not None:
        label = next(l for limit, l in EU_AQI if aq["european_aqi"] <= limit)
        head = f"European AQI: *{aq['european_aqi']}* ({label})"
    else:
        head = f"Index: *{aq.get('index_1_5')}* / 5"
    fmt = lambda k: "N/A" if comp.get(k) is None else f"{comp[k]:.1f}"
    return (f"🌫️ *Air Quality — {_place(d['location'])}*\n\n{head}\n\n"
            f"PM2.5: `{fmt('pm2_5')}` μg/m³\nPM10:  `{fmt('pm10')}` μg/m³\nNO₂:   `{fmt('no2')}` μg/m³\n"
            f"SO₂:   `{fmt('so2')}` μg/m³\nCO:    `{fmt('co')}` μg/m³\nO₃:    `{fmt('o3')}` μg/m³")

def format_alerts(d: dict) -> str:
    loc, u = d["location"], d["units"]
    if not d["alerts"]:
        return f"✅ No weather warnings for *{_place(loc)}* in the next 3 days."
    unit_for = {"temperature": u["temperature"], "wind_gust": f" {u['speed']}",
                "precipitation_rate": f" {u['precipitation_rate']}"}
    msg = f"🚨 *Weather Warnings — {_place(loc)}*\n\n"
    for a in d["alerts"]:
        start, end = _local(a["start"], loc), _local(a["end"], loc)
        peak = f"\n   Peak: {_num(a['peak'], 1)}{unit_for.get(a['peak_field'], '')}" if a.get("peak") is not None else ""
        msg += f"{SEVERITY_ICON[a['severity']]} *{a['event']}*\n   🕒 {start:%a %H:%M} — {end:%a %H:%M}{peak}\n\n"
    return msg

def weather_buttons(lat: float, lon: float, name: str) -> InlineKeyboardMarkup:
    p = f"{lat:.3f}:{lon:.3f}"
    name = name.encode("utf-8")[:48].decode("utf-8", "ignore")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺️ Map", callback_data=f'map:{p}'),
         InlineKeyboardButton("🔄 Refresh", callback_data=f'now:{p}')],
        [InlineKeyboardButton("⏰ 24h", callback_data=f'hourly:{p}'),
         InlineKeyboardButton("📅 5-day", callback_data=f'daily:{p}')],
        [InlineKeyboardButton("💨 AQI", callback_data=f'aqi:{p}'),
         InlineKeyboardButton("☀️ UV", callback_data=f'uv:{p}')],
        [InlineKeyboardButton("🚨 Alerts", callback_data=f'alerts:{p}'),
         InlineKeyboardButton("❤️ Save", callback_data=f'savefav:{name[:40]}')],
    ])


# ─── Generic "city argument" helper ──────────────────────────────────────────



async def reply_weather(message, user_id: int, city=None, lat=None, lon=None, edit_query=None):
    units = get_user_units(user_id)
    try:
        d = await call(api.current, units=units, **where(city, lat, lon))
    except SkyMateError as e:
        text = error_text(e, f"*{md(city)}*" if city else "")
        if e.status == 404 and city:
            try:
                hits = await call(api.geocode, city.split(',')[0][:3], 5)
                if hits:
                    text += "\n\nDid you mean:\n" + "\n".join(f"• {h['name']}, {h['country']}" for h in hits)
            except SkyMateError:
                pass
        if edit_query:
            await edit_query.edit_message_text(text, parse_mode='Markdown')
        else:
            await message.reply_markdown(text)
        return
    loc = d["location"]
    markup = weather_buttons(loc["lat"], loc["lon"], loc["name"])
    if edit_query:
        await edit_query.edit_message_text(format_current(d), parse_mode='Markdown', reply_markup=markup)
    else:
        await message.reply_markdown(format_current(d), reply_markup=markup)


# ─── Commands ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🌤 Weather", switch_inline_query_current_chat=''),
         InlineKeyboardButton("📅 Forecast", callback_data='forecast_main')],
        [InlineKeyboardButton("❤️ Favorites", callback_data='show_favorites'),
         InlineKeyboardButton("🚨 Alerts", callback_data='alerts_main')],
        [InlineKeyboardButton("📬 Subscribe", callback_data='subscribe_start'),
         InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
        [InlineKeyboardButton(f"⭐ Get Premium — {PREMIUM_STARS} Stars/month", callback_data='premium')],
    ]
    uid = update.effective_user.id
    plan = "⭐ Premium" if is_premium(uid) else "Free (see /plans)"
    await update.message.reply_text(
        f"👋 Welcome, *{update.effective_user.first_name}*!\n\n"
        "Send any city name for the weather, or use the menu.\n\n"
        f"Your plan: *{plan}*",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))


PLANS_TEXT = (
    "💳 *SkyMate plans*\n\n"
    "*Free*\n"
    "• Current weather with real station measurements\n"
    "• 5-day and 24-hour forecasts, warnings, UV, air quality, maps\n"
    "• Daily morning report for 1 city\n"
    f"• Up to {FREE_FAVORITES} favorite cities, {FREE_HISTORY_DAYS} days of history\n\n"
    "*⭐ Premium* — {price} Stars per month\n"
    "• Everything in Free\n"
    "• 🚨 Severe-weather warnings pushed to you automatically\n"
    "• 📅 10-day forecasts\n"
    "• 📈 Up to a year of measured history per chart\n"
    "• ❤️ Unlimited favorites\n"
    "• 💻 Premium in the SkyMate desktop app\n\n"
    "Cancel anytime in Telegram: Settings → My Stars."
)


async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = PLANS_TEXT.replace("{price}", str(PREMIUM_STARS))
    if is_premium(uid):
        await update.message.reply_markdown(text + f"\n\n✅ You're Premium until {premium_until(uid):%d %b %Y}.")
        return
    await update.message.reply_markdown(text, reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"⭐ Get Premium — {PREMIUM_STARS} Stars/month", callback_data='premium')]]))

async def location_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_kb = [[KeyboardButton("📍 Share Location", request_location=True)]]
    await update.message.reply_text(
        "📍 Tap the button to share your location (works on phone only).",
        reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_markdown(
        "⚡ *Commands*\n\n"
        "/weather `<city>` — Current conditions\n"
        "/forecast `<city>` — 5-day forecast\n"
        "/week `<city>` — 10-day forecast\n"
        "/hourly `<city>` — Next 24 hours\n"
        "/aqi `<city>` — Air quality\n"
        "/uv `<city>` — UV index\n"
        "/alerts `<city>` — Weather warnings\n"
        "/radar `<city>` — Weather map\n"
        "/history `<city> [days]` — Measured history chart\n"
        "/stations `<city>` — Nearby measuring stations\n"
        "/favorites — Saved locations\n"
        "/addfavorite — Add a location\n"
        "/removefavorite — Remove a location\n"
        "/subscribe — Daily 8 AM updates\n"
        "/units — Toggle °C / °F\n"
        "/settings — Preferences\n"
        "/location — Share your location (phone only)\n"
        "/plans — Free vs ⭐ Premium\n"
        "/premium — ⭐ Get Premium\n"
        "/app — Desktop app key\n"
        "/paysupport — Payment help\n\n"
        "Or just type any city name.")

async def units_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    new = 'imperial' if get_user_units(uid) == 'metric' else 'metric'
    set_user_units(uid, new)
    label = "Imperial (°F, mph)" if new == 'imperial' else "Metric (°C, m/s)"
    await update.message.reply_text(f"✅ Units set to *{label}*", parse_mode='Markdown')

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_settings(update.effective_user.id, update.message, edit=False)

async def _send_settings(user_id: int, target, edit: bool):
    units = get_user_units(user_id)
    unit_label = "Metric (°C)" if units == 'metric' else "Imperial (°F)"
    sub = get_subscription(user_id)
    sub_label = f"📬 {sub['city']} (tap to manage)" if sub else "📬 Not subscribed (tap to subscribe)"
    keyboard = [[InlineKeyboardButton(f"🌡 {unit_label} — tap to switch", callback_data='toggle_units')],
                [InlineKeyboardButton(sub_label, callback_data='manage_sub')]]
    if edit:
        await target.edit_message_text("⚙️ *Settings*", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await target.reply_text("⚙️ *Settings*", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message or update.edited_message
    if not message:
        return
    if context.args is not None and not context.args:
        await message.reply_text("Usage: /weather <city>")
        return
    raw = city_arg(context) or (message.text or '').strip()
    if not raw or raw.startswith('/') or raw.startswith('@') or raw == "📍 Share Location":
        return
    await reply_weather(message, update.effective_user.id, city=raw)


async def _simple(update, context, usage, fn, fmt, **kw):
    city = city_arg(context)
    if not city:
        await update.message.reply_text(f"Usage: {usage} <city>")
        return
    try:
        d = await call(fn, q=city, **kw)
    except SkyMateError as e:
        await update.message.reply_markdown(error_text(e, f"*{md(city)}*"))
        return
    await update.message.reply_markdown(fmt(d))

async def forecast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _simple(update, context, "/forecast", api.daily, format_daily, days=5, units=get_user_units(update.effective_user.id))

async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_premium(update.effective_user.id):
        await update.message.reply_text(PREMIUM_ONLY)
        return
    await _simple(update, context, "/week", api.daily, format_daily, days=10, units=get_user_units(update.effective_user.id))

async def hourly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _simple(update, context, "/hourly", api.hourly, format_hourly, hours=24, units=get_user_units(update.effective_user.id))

async def aqi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _simple(update, context, "/aqi", api.air_quality, format_aqi)

async def uv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _simple(update, context, "/uv", api.uv, format_uv)

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _simple(update, context, "/alerts", api.alerts, format_alerts, units=get_user_units(update.effective_user.id))


async def send_map(message, city=None, lat=None, lon=None):
    try:
        png = await call(api.map_png, **where(city, lat, lon))
    except SkyMateError as e:
        await message.reply_text(error_text(e) if e.status != 503 else "🗺️ Map will be available once the first forecast download completes.")
        return
    await message.reply_photo(photo=png, caption=f"🗺️ Temperature & wind{' — ' + city if city else ''}")

async def radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = city_arg(context)
    if not city:
        await update.message.reply_text("Usage: /radar <city>")
        return
    await send_map(update.message, city=city)

def _chart(times, temps, unit: str, title: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(times, temps, color='#4fc3f7', linewidth=1.8, marker='o', ms=2)
    ax.fill_between(times, temps, min(temps), alpha=0.2, color='#4fc3f7')
    fig.autofmt_xdate()
    ax.set_ylabel(f"Temperature ({unit})")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120)
    plt.close(fig)
    buf.seek(0)
    return buf


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/history <city> [days] — measured station readings; model history only if no station exists."""
    args = context.args or []
    days = 7
    if args and args[-1].isdigit():
        days = max(1, min(366, int(args.pop())))
    city = ' '.join(args).strip()
    if not city:
        await update.message.reply_text("Usage: /history <city> [days, up to 366]")
        return
    if days > FREE_HISTORY_DAYS and not is_premium(update.effective_user.id):
        await update.message.reply_text(f"Free plan shows the last {FREE_HISTORY_DAYS} days. {PREMIUM_ONLY}")
        return
    units = get_user_units(update.effective_user.id)
    try:
        d = await call(api.observation_history, q=city, days=days, units=units)
        st = d["station"]
        pts = [(datetime.fromisoformat(o["time"]), o["temperature"]) for o in d["observations"]
               if o["temperature"] is not None]
        label = f"Measured at {st['name']}"
        cov = d["coverage"]
        note = f"\nThis station's archive: {cov['readings']:,} readings since {cov['from'][:4]}" if cov["from"] else ""
    except SkyMateError as e:
        if e.status != 404:
            await update.message.reply_markdown(error_text(e, f"*{md(city)}*"))
            return
        try:
            d = await call(api.history, q=city, days=min(days, 90), units=units)
        except SkyMateError as e2:
            await update.message.reply_markdown(error_text(e2, f"*{md(city)}*"))
            return
        pts = [(datetime.fromisoformat(p["time"]), p["temperature"]) for p in d["history"] if p["temperature"] is not None]
        label, note = "Model estimate (no station nearby)", ""
    if len(pts) < 2:
        await update.message.reply_text("❌ Not enough data for that period yet.")
        return
    times, temps = zip(*pts)
    unit = "°F" if units == "imperial" else "°C"
    title = f"Last {days} days — {label}"
    await update.message.reply_photo(
        photo=_chart(times, temps, unit, title),
        caption=f"📈 {title}\nMin {min(temps):.1f}{unit} · Max {max(temps):.1f}{unit} · {len(temps)} readings{note}")


async def stations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = city_arg(context)
    if not city:
        await update.message.reply_text("Usage: /stations <city>")
        return
    units = get_user_units(update.effective_user.id)
    try:
        d = await call(api.observations_latest, q=city, radius_km=100, limit=8, units=units)
    except SkyMateError as e:
        await update.message.reply_markdown(error_text(e, f"*{md(city)}*"))
        return
    if not d["stations"]:
        await update.message.reply_markdown(f"No weather stations reported near *{_place(d['location'])}* in the last 3 hours.")
        return
    u = {"temperature": "°F" if units == "imperial" else "°C", "speed": "mph" if units == "imperial" else "m/s"}
    msg = f"📡 *Measuring stations near {_place(d['location'])}*\n\n"
    for h in d["stations"]:
        st, o = h["station"], h["observation"]
        kind = "✈️" if st["kind"] == "airport" else "🏛"
        msg += (f"{kind} *{md(st['name'])}* — {st['distance_km']} km\n"
                f"   {_num(o['temperature'], 1)}{u['temperature']}, wind {_num(o.get('wind_speed'), 1)} {u['speed']}, "
                f"{_age(o['age_minutes'])}\n")
    await update.message.reply_markdown(msg + "\n✈️ airport  🏛 national weather service")


# ─── Favorites ────────────────────────────────────────────────────────────────

def favorites_markup(uid: int):
    favs = get_user_favorites(uid)
    kb = [[InlineKeyboardButton(f"🌤 {c}", callback_data=f'fav:{i}')] for i, c in enumerate(favs)]
    kb.append([InlineKeyboardButton("➕ Add", callback_data='add_fav_inline')] +
              ([InlineKeyboardButton("➖ Remove", callback_data='remove_fav_inline')] if favs else []))
    return favs, InlineKeyboardMarkup(kb)

async def favorites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    favs, markup = favorites_markup(update.effective_user.id)
    await update.message.reply_text("❤️ *Favorites:*" if favs else "No favorites yet.", parse_mode='Markdown',
                                    reply_markup=markup)

async def add_favorite_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏙️ Enter city name to add:")
    return STATE_ADD_FAVORITE

async def _add_favorite(message, uid: int, raw: str):
    if len(get_user_favorites(uid)) >= FREE_FAVORITES and not is_premium(uid):
        await message.reply_text(f"Free plan saves up to {FREE_FAVORITES} favorites. {PREMIUM_ONLY}")
        return
    try:
        hits = await call(api.geocode, raw, 1)
    except SkyMateError as e:
        await message.reply_text(error_text(e))
        return
    if not hits:
        await message.reply_markdown(f"❌ *{md(raw)}* not found.")
        return
    name = hits[0]["name"]
    add_user_favorite(uid, name)
    await message.reply_markdown(f"✅ *{name}, {hits[0]['country']}* added to favorites!")

async def add_favorite_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _add_favorite(update.message, update.effective_user.id, update.message.text.strip())
    return ConversationHandler.END

async def remove_favorite_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    favs = get_user_favorites(update.effective_user.id)
    if not favs:
        await update.message.reply_text("No favorites to remove.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    await update.message.reply_text("Select city to remove:",
                                    reply_markup=ReplyKeyboardMarkup([[c] for c in favs], one_time_keyboard=True))
    return STATE_REMOVE_FAVORITE

async def remove_favorite_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text.strip()
    remove_user_favorite(update.effective_user.id, city)
    await update.message.reply_text(f"✅ *{city}* removed.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('awaiting', None)
    await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ─── Subscriptions ────────────────────────────────────────────────────────────

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sub = get_subscription(update.effective_user.id)
    if sub:
        text = f"📬 Subscribed for *{sub['city']}* at 8 AM UTC."
        kb = [[InlineKeyboardButton("🔄 Change city", callback_data='subscribe_start'),
               InlineKeyboardButton("❌ Unsubscribe", callback_data='unsubscribe')]]
    else:
        text = "📬 Subscribe to a daily weather report at 8 AM UTC."
        kb = [[InlineKeyboardButton("✅ Subscribe", callback_data='subscribe_start')]]
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def send_daily_update(context):
    job = context.job
    try:
        now = await call(api.current, q=job.data['city'], units=job.data['units'])
        alerts = await call(api.alerts, q=job.data['city'], units=job.data['units'])
    except SkyMateError as e:
        logger.warning("Daily update for %s failed: %s", job.data['city'], e)
        return
    msg = "🌅 *Good morning! Your daily weather*\n\n" + format_current(now)
    if alerts["alerts"]:
        msg += "\n\n" + format_alerts(alerts)
    await context.bot.send_message(job.chat_id, text=msg, parse_mode='Markdown')

def _next_8am():
    t = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    return t if t > datetime.now(timezone.utc) else t + timedelta(days=1)

def schedule_daily(job_queue, uid, chat_id, city, units):
    for job in job_queue.get_jobs_by_name(f'daily_{uid}'):
        job.schedule_removal()
    job_queue.run_repeating(send_daily_update, interval=86400, first=_next_8am(),
                            data={'city': city, 'units': units}, chat_id=chat_id, name=f'daily_{uid}')


# ─── Location ─────────────────────────────────────────────────────────────────

async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    await update.message.reply_text("📍 Location received.", reply_markup=ReplyKeyboardRemove())
    await reply_weather(update.message, update.effective_user.id, lat=loc.latitude, lon=loc.longitude)


# ─── Buttons ──────────────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    d = query.data
    uid = query.from_user.id

    if d.startswith('savefav:'):
        name = d.split(':', 1)[1]
        if len(get_user_favorites(uid)) >= FREE_FAVORITES and not is_premium(uid) and name not in get_user_favorites(uid):
            await query.answer(f"Free plan saves up to {FREE_FAVORITES} favorites. See /premium", show_alert=True)
            return
        add_user_favorite(uid, name)
        await query.answer(f"❤️ {name} saved!", show_alert=True)
        return
    await query.answer()

    if d == 'settings':
        await _send_settings(uid, query, edit=True)
    elif d == 'toggle_units':
        set_user_units(uid, 'imperial' if get_user_units(uid) == 'metric' else 'metric')
        await _send_settings(uid, query, edit=True)
    elif d == 'manage_sub':
        sub = get_subscription(uid)
        if sub:
            text = f"📬 Subscribed for *{sub['city']}* at 8 AM UTC."
            kb = [[InlineKeyboardButton("🔄 Change city", callback_data='subscribe_start'),
                   InlineKeyboardButton("❌ Unsubscribe", callback_data='unsubscribe')],
                  [InlineKeyboardButton("⬅️ Back", callback_data='settings')]]
        else:
            text = "📬 No active subscription."
            kb = [[InlineKeyboardButton("✅ Subscribe", callback_data='subscribe_start')],
                  [InlineKeyboardButton("⬅️ Back", callback_data='settings')]]
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'show_favorites':
        favs, markup = favorites_markup(uid)
        await query.message.reply_text("❤️ *Favorites:*" if favs else "No favorites yet.", parse_mode='Markdown',
                                       reply_markup=markup)
    elif d == 'add_fav_inline':
        context.user_data['awaiting'] = 'add_fav'
        await query.message.reply_text("🏙️ Send the city name to save:")
    elif d == 'remove_fav_inline':
        favs = get_user_favorites(uid)
        kb = [[InlineKeyboardButton(f"✕ {c}", callback_data=f'delfav:{i}')] for i, c in enumerate(favs)]
        await query.message.reply_text("Tap a city to remove:" if favs else "No favorites to remove.",
                                       reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    elif d.startswith('delfav:'):
        favs = get_user_favorites(uid)
        i = int(d.split(':')[1])
        if i < len(favs):
            remove_user_favorite(uid, favs[i])
            await query.edit_message_text(f"✅ *{favs[i]}* removed.", parse_mode='Markdown')
    elif d.startswith('fav:'):
        favs = get_user_favorites(uid)
        i = int(d.split(':')[1])
        if i < len(favs):
            await reply_weather(query.message, uid, city=favs[i], edit_query=query)
    elif d == 'premium':
        await send_premium_offer(query.message, uid, context.bot)
    elif d == 'forecast_main':
        context.user_data['awaiting'] = 'forecast'
        await query.message.reply_text("🏙️ Send a city name for the forecast:")
    elif d == 'alerts_main':
        context.user_data['awaiting'] = 'alerts'
        await query.message.reply_text("🏙️ Send a city name for weather warnings:")
    elif d == 'subscribe_start':
        context.user_data['awaiting'] = 'subscribe_city'
        context.user_data['sub_chat_id'] = query.message.chat_id
        await query.message.reply_text("🏙️ Which city do you want daily updates for?")
    elif d == 'unsubscribe':
        for job in context.job_queue.get_jobs_by_name(f'daily_{uid}'):
            job.schedule_removal()
        delete_subscription(uid)
        await query.edit_message_text("✅ Unsubscribed from daily updates.")
    elif ':' in d:
        await _detail_button(query, uid, d)


async def _detail_button(query, uid: int, d: str):
    kind, lat, lon = d.split(':')
    lat, lon = float(lat), float(lon)
    units = get_user_units(uid)
    if kind == 'map':
        await send_map(query.message, lat=lat, lon=lon)
        return
    if kind == 'now':
        await reply_weather(query.message, uid, lat=lat, lon=lon, edit_query=query)
        return
    back = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f'now:{lat:.3f}:{lon:.3f}')]])
    try:
        if kind == 'hourly':
            text = format_hourly(await call(api.hourly, lat=lat, lon=lon, hours=24, units=units))
        elif kind == 'daily':
            text = format_daily(await call(api.daily, lat=lat, lon=lon, days=5, units=units))
        elif kind == 'aqi':
            text = format_aqi(await call(api.air_quality, lat=lat, lon=lon))
        elif kind == 'uv':
            text = format_uv(await call(api.uv, lat=lat, lon=lon))
        elif kind == 'alerts':
            text = format_alerts(await call(api.alerts, lat=lat, lon=lon, units=units))
        else:
            return
    except SkyMateError as e:
        text = error_text(e)
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=back)


# ─── Premium (Telegram Stars) ─────────────────────────────────────────────────

PREMIUM_ONLY = "⭐ This is a Premium feature. See /premium"


async def send_premium_offer(message, uid: int, bot):
    until = premium_until(uid)
    if is_premium(uid) and until:
        await message.reply_markdown(
            PREMIUM_BENEFITS + f"\n✅ You're Premium until *{until:%d %b %Y}*.\n"
            "Manage or cancel the subscription in Telegram: Settings → My Stars.")
        return
    link = await bot.create_invoice_link(
        title="SkyMate Premium",
        description="Severe-weather warnings, 10-day forecasts, full measured history, unlimited favorites "
                    "and Premium in the desktop app. Renews every 30 days; cancel anytime.",
        payload=f"premium:{uid}", provider_token="", currency="XTR",
        prices=[LabeledPrice("Premium (30 days)", PREMIUM_STARS)],
        subscription_period=30 * 24 * 3600)
    await message.reply_markdown(
        PREMIUM_BENEFITS + f"\nPrice: *{PREMIUM_STARS} ⭐ Stars per month*.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"⭐ Subscribe — {PREMIUM_STARS} Stars/month", url=link)]]))


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_premium_offer(update.message, update.effective_user.id, context.bot)


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    ok = q.currency == "XTR" and q.invoice_payload == f"premium:{q.from_user.id}"
    await q.answer(ok=ok, error_message=None if ok else "This invoice isn't valid anymore. Send /premium again.")


async def sync_app_plan(uid: int):
    if not has_app_key(uid):
        return
    plan = "premium" if is_premium(uid) else "app_free"
    try:
        await call(admin_api.set_plan_by_name, f"tg:{uid}", plan)
        with store.tx("bot") as conn:
            conn.execute("UPDATE app_keys SET plan=? WHERE user_id=?", (plan, uid))
    except SkyMateError as e:
        logger.warning("Could not update app plan for %s: %s", uid, e)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    uid = update.effective_user.id
    now = datetime.now(timezone.utc)
    if sp.currency != "XTR" or sp.total_amount < PREMIUM_STARS or sp.invoice_payload != f"premium:{uid}":
        logger.error("Rejected unexpected payment from %s: %s %s payload=%s", uid, sp.total_amount, sp.currency,
                     sp.invoice_payload)
        return
    if sp.subscription_expiration_date:
        until = sp.subscription_expiration_date
    else:
        current = premium_until(uid)
        until = max(current, now) + timedelta(days=30) if current else now + timedelta(days=30)
    grant_premium(uid, until, sp.telegram_payment_charge_id, sp.total_amount, bool(sp.is_recurring))
    await sync_app_plan(uid)
    logger.info("Premium payment: user %s, %s stars, until %s", uid, sp.total_amount, until)
    if sp.is_first_recurring is False:
        return
    await update.message.reply_markdown(
        f"🎉 *Welcome to SkyMate Premium!* Active until {until:%d %b %Y}.\n\n"
        "• Set your city for severe-weather warnings: /subscribe\n"
        "• 10-day forecast: /week `<city>`\n"
        "• Desktop app key: /app")


async def paysupport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = SUPPORT_CONTACT or "the bot owner"
    await update.message.reply_text(
        "💬 Payment support\n\n"
        f"For problems with a Premium payment or a refund request, contact {contact} and include the date "
        "of the payment. You can cancel your subscription anytime in Telegram: Settings → My Stars.")


async def refund_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: /refund <user_id> — refunds the user's latest Premium payment."""
    if update.effective_user.id != BOT_ADMIN_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /refund <user_id>")
        return
    uid = int(context.args[0])
    with store.tx("bot") as conn:
        row = conn.execute("SELECT charge_id FROM payments WHERE user_id=? AND refunded=0 ORDER BY created_at DESC LIMIT 1",
                           (uid,)).fetchone()
    if not row:
        await update.message.reply_text("No refundable payment found for that user.")
        return
    try:
        await context.bot.refund_star_payment(uid, row[0])
    except Exception as e:
        await update.message.reply_text(f"Refund failed: {e}")
        return
    with store.tx("bot") as conn:
        conn.execute("UPDATE payments SET refunded=1 WHERE charge_id=?", (row[0],))
        conn.execute("UPDATE premium SET until=? WHERE user_id=?", (int(datetime.now(timezone.utc).timestamp()), uid))
    await sync_app_plan(uid)
    await update.message.reply_text(f"✅ Refunded {row[0]} to {uid}; Premium removed.")


async def premiumstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_ADMIN_ID:
        return
    now = int(datetime.now(timezone.utc).timestamp())
    with store.tx("bot") as conn:
        active = conn.execute("SELECT COUNT(*) FROM premium WHERE until > ?", (now,)).fetchone()[0]
        month = conn.execute("SELECT COUNT(*), COALESCE(SUM(stars),0) FROM payments WHERE refunded=0 AND "
                             "created_at >= ?", (store.ago(30),)).fetchone()
        total = conn.execute("SELECT COALESCE(SUM(stars),0) FROM payments WHERE refunded=0").fetchone()[0]
        users = conn.execute("SELECT COUNT(*) FROM user_settings").fetchone()[0]
    await update.message.reply_text(
        f"⭐ Premium stats\n\nActive subscribers: {active}\nLast 30 days: {month[0]} payments, {month[1]} Stars\n"
        f"All time: {total} Stars\nUsers with saved settings: {users}")


async def app_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    plan = "premium" if is_premium(uid) else "app_free"
    try:
        await call(admin_api.revoke_by_name, f"tg:{uid}")
        key = await call(admin_api.create_key, f"tg:{uid}", plan)
    except SkyMateError as e:
        logger.error("App key creation failed: %s", e)
        await update.message.reply_text("⚠️ Couldn't create your app key right now. Please try again later.")
        return
    with store.tx("bot") as conn:
        conn.execute("INSERT INTO app_keys(user_id, plan, created_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE "
                     "SET plan=excluded.plan, created_at=excluded.created_at", (uid, plan, store.now()))
    server = PUBLIC_API_URL or api.base
    download = f"\n\n⬇️ Download: {APP_DOWNLOAD_URL}" if APP_DOWNLOAD_URL else ""
    tier = "⭐ Premium" if plan == "premium" else "Free (upgrade with /premium)"
    await update.message.reply_markdown(
        f"💻 *Your SkyMate desktop app key*\n\n`{key}`\n\n"
        f"Server: `{server}`\nPlan: {tier}\n\n"
        "Open the app, click ⚙, paste the key. Keep it private: anyone with it can use your plan. "
        "Sending /app again replaces the old key." + download)


async def premium_maintenance(context: ContextTypes.DEFAULT_TYPE):
    """Hourly: push new severe-weather warnings to Premium users and keep app key plans in sync."""
    now = int(datetime.now(timezone.utc).timestamp())
    with store.tx("bot") as conn:
        premium_users = {r[0] for r in conn.execute("SELECT user_id FROM premium WHERE until > ?", (now,))}
        subs = conn.execute("SELECT user_id, chat_id, city, units FROM user_subscriptions").fetchall()
        app_rows = conn.execute("SELECT user_id, plan FROM app_keys").fetchall()
    for uid, plan in app_rows:
        if plan != ("premium" if uid in premium_users else "app_free"):
            await sync_app_plan(uid)
    for uid, chat_id, city, units in subs:
        if uid not in premium_users:
            continue
        try:
            d = await call(api.alerts, q=city, units=units)
        except SkyMateError:
            continue
        fresh = []
        with store.tx("bot") as conn:
            for a in d["alerts"]:
                if a["severity"] == "minor":
                    continue
                key = f"{city}:{a['id']}:{a['start'][:10]}"
                if conn.execute("INSERT INTO alert_sent(user_id, alert_key, sent_at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                                (uid, key, store.now())).rowcount:
                    fresh.append(a)
        if fresh:
            d["alerts"] = fresh
            try:
                await context.bot.send_message(chat_id, format_alerts(d), parse_mode='Markdown')
            except Exception as e:
                logger.warning("Alert push to %s failed: %s", uid, e)


# ─── Free-text dispatcher ─────────────────────────────────────────────────────

async def text_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.pop('awaiting', None)
    text = update.message.text.strip()
    if len(text) > MAX_TEXT:
        await update.message.reply_text("That's too long for a city name.")
        return
    uid = update.effective_user.id

    if awaiting == 'subscribe_city':
        chat_id = context.user_data.pop('sub_chat_id', update.effective_chat.id)
        units = get_user_units(uid)
        try:
            hits = await call(api.geocode, text, 1)
        except SkyMateError as e:
            await update.message.reply_text(error_text(e))
            return
        if not hits:
            context.user_data['awaiting'] = 'subscribe_city'
            await update.message.reply_markdown(f"❌ *{md(text)}* not found. Please send another city name:")
            return
        city = f"{hits[0]['name']}, {hits[0]['country']}"
        schedule_daily(context.job_queue, uid, chat_id, city, units)
        save_subscription(uid, chat_id, city, units)
        await update.message.reply_markdown(f"✅ Subscribed! Daily report for *{city}* at 8:00 AM UTC.")
    elif awaiting == 'add_fav':
        await _add_favorite(update.message, uid, text)
    elif awaiting in ('forecast', 'alerts'):
        context.args = text.split()
        await (forecast_command if awaiting == 'forecast' else alerts_command)(update, context)
    else:
        await weather_command(update, context)


# ─── Inline mode ──────────────────────────────────────────────────────────────

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.inline_query.query.strip()
    if len(q) < 2:
        await update.inline_query.answer([InlineQueryResultArticle(
            id='0', title="Type a city name…",
            input_message_content=InputTextMessageContent("Type a city name to get the weather."))])
        return
    units = get_user_units(update.inline_query.from_user.id)
    try:
        d = await call(api.current, q=q, units=units)
        c = d["current"]
        results = [InlineQueryResultArticle(
            id='1', title=f"{_place_plain(d['location'])}: {_num(c['temperature'])}{d['units']['temperature']}",
            description=c['description'].capitalize(),
            input_message_content=InputTextMessageContent(format_current(d), parse_mode='Markdown'))]
    except SkyMateError:
        results = [InlineQueryResultArticle(
            id='0', title=f"'{q}' not found",
            input_message_content=InputTextMessageContent(f"No weather found for '{q}'."))]
    await update.inline_query.answer(results, cache_time=60)


async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error: %s", context.error, exc_info=context.error)


BOT_COMMANDS = [
    ("weather", "Current weather for a city"), ("forecast", "5-day forecast"), ("week", "⭐ 10-day forecast"),
    ("hourly", "Next 24 hours"), ("alerts", "Weather warnings"), ("stations", "Nearby measuring stations"),
    ("history", "Measured history chart"), ("aqi", "Air quality"), ("uv", "UV index"), ("radar", "Weather map"),
    ("favorites", "Saved cities"), ("subscribe", "Daily report"), ("premium", "⭐ SkyMate Premium"),
    ("plans", "Free vs Premium"),
    ("app", "Desktop app key"), ("settings", "Units and subscription"), ("paysupport", "Payment help"),
    ("help", "All commands"),
]


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u or u.is_bot:
        return
    with store.tx("bot") as conn:
        conn.execute(
            "INSERT INTO users(user_id, username, first_name, last_name, language, first_seen, last_seen, actions) "
            "VALUES (?,?,?,?,?,?,?,1) ON CONFLICT(user_id) DO UPDATE SET "
            "username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name, "
            "language=excluded.language, last_seen=excluded.last_seen, "
            "first_seen=COALESCE(users.first_seen, excluded.first_seen), actions=users.actions+1",
            (u.id, u.username, u.first_name, u.last_name, u.language_code, store.now(), store.now()))


async def restore_subscriptions(app):
    try:
        await app.bot.set_my_commands(BOT_COMMANDS)
    except Exception as e:
        logger.warning("Could not register command menu: %s", e)
    subs = get_all_subscriptions()
    for uid, chat_id, city, units in subs:
        schedule_daily(app.job_queue, uid, chat_id, city, units)
    if subs:
        logger.info("Restored %d subscription(s).", len(subs))


def build_app():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(restore_subscriptions).build()
    app.add_handler(TypeHandler(Update, rate_limit), group=-2)
    app.add_handler(TypeHandler(Update, track_user), group=-1)

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler('addfavorite', add_favorite_start)],
        states={STATE_ADD_FAVORITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_favorite_end)]},
        fallbacks=[CommandHandler('cancel', cancel)]))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler('removefavorite', remove_favorite_start)],
        states={STATE_REMOVE_FAVORITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_favorite_end)]},
        fallbacks=[CommandHandler('cancel', cancel)]))

    for name, fn in [("start", start), ("help", help_command), ("location", location_command),
                     ("units", units_command), ("settings", settings_command), ("weather", weather_command),
                     ("forecast", forecast_command), ("week", week_command), ("hourly", hourly_command),
                     ("aqi", aqi_command), ("uv", uv_command), ("alerts", alerts_command),
                     ("radar", radar_command), ("history", history_command), ("stations", stations_command),
                     ("favorites", favorites_command),
                     ("subscribe", subscribe_command), ("cancel", cancel), ("premium", premium_command), ("plans", plans_command),
                     ("paysupport", paysupport_command), ("app", app_command), ("refund", refund_command),
                     ("premiumstats", premiumstats_command), ("admin", admin_command)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.job_queue.run_repeating(premium_maintenance, interval=3600, first=120, name="premium_maintenance")
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_dispatcher))
    app.add_error_handler(error_handler)
    return app


def main():
    """Local mode: long polling. On a web host the API server runs the bot by webhook instead."""
    build_app().run_polling(drop_pending_updates=False)


if __name__ == '__main__':
    main()
