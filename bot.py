import asyncio
import io
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytz
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update,
)
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
    InlineQueryHandler, MessageHandler, filters,
)

from skymate_client import SkyMate, SkyMateError

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DB_PATH = 'bot_data.db'
DEFAULT_UNITS = 'metric'
api = SkyMate()

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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS user_settings (user_id INTEGER PRIMARY KEY, units TEXT DEFAULT 'metric')")
        conn.execute("CREATE TABLE IF NOT EXISTS user_favorites (user_id INTEGER, city TEXT, PRIMARY KEY (user_id, city))")
        conn.execute("CREATE TABLE IF NOT EXISTS user_subscriptions "
                     "(user_id INTEGER PRIMARY KEY, chat_id INTEGER, city TEXT, units TEXT)")

def get_user_units(user_id: int) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute('SELECT units FROM user_settings WHERE user_id=?', (user_id,)).fetchone()
    return row[0] if row else DEFAULT_UNITS

def set_user_units(user_id: int, units: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT OR REPLACE INTO user_settings VALUES (?,?)', (user_id, units))

def get_user_favorites(user_id: int) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute('SELECT city FROM user_favorites WHERE user_id=? ORDER BY rowid', (user_id,)).fetchall()
    return [r[0] for r in rows]

def add_user_favorite(user_id: int, city: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT OR IGNORE INTO user_favorites VALUES (?,?)', (user_id, city))

def remove_user_favorite(user_id: int, city: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM user_favorites WHERE user_id=? AND city=?', (user_id, city))

def get_subscription(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute('SELECT chat_id, city, units FROM user_subscriptions WHERE user_id=?', (user_id,)).fetchone()
    return {'chat_id': row[0], 'city': row[1], 'units': row[2]} if row else None

def get_all_subscriptions():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute('SELECT user_id, chat_id, city, units FROM user_subscriptions').fetchall()

def save_subscription(user_id: int, chat_id: int, city: str, units: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT OR REPLACE INTO user_subscriptions VALUES (?,?,?,?)', (user_id, chat_id, city, units))

def delete_subscription(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
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

def _place(loc: dict) -> str:
    return f"{loc['name']}, {loc['country']}" if loc.get("country") else loc["name"]

def _freshness(meta: dict) -> str:
    if meta.get("stale"):
        return f"\n\n⚠️ _Offline mode: forecast issued {round(meta['data_age_hours'])} h ago_"
    return ""

def format_current(d: dict) -> str:
    loc, c, u = d["location"], d["current"], d["units"]
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

def city_arg(context) -> str | None:
    return ' '.join(context.args).strip() if context.args else None


async def reply_weather(message, user_id: int, city=None, lat=None, lon=None, edit_query=None):
    units = get_user_units(user_id)
    try:
        d = await call(api.current, units=units, **where(city, lat, lon))
    except SkyMateError as e:
        text = error_text(e, f"*{city}*" if city else "")
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
    ]
    await update.message.reply_text(
        f"👋 Welcome, *{update.effective_user.first_name}*!\n\nSend any city name or use the menu:",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

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
        "/history `<city>` — Last 7 days chart\n"
        "/favorites — Saved locations\n"
        "/addfavorite — Add a location\n"
        "/removefavorite — Remove a location\n"
        "/subscribe — Daily 8 AM updates\n"
        "/units — Toggle °C / °F\n"
        "/settings — Preferences\n"
        "/location — Share your location (phone only)\n\n"
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
        await update.message.reply_markdown(error_text(e, f"*{city}*"))
        return
    await update.message.reply_markdown(fmt(d))

async def forecast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _simple(update, context, "/forecast", api.daily, format_daily, days=5, units=get_user_units(update.effective_user.id))

async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = city_arg(context)
    if not city:
        await update.message.reply_text("Usage: /history <city>")
        return
    units = get_user_units(update.effective_user.id)
    try:
        d = await call(api.history, q=city, days=7, units=units)
    except SkyMateError as e:
        await update.message.reply_markdown(error_text(e, f"*{city}*"))
        return
    pts = [(_local(p["time"], d["location"]), p["temperature"]) for p in d["history"] if p["temperature"] is not None]
    if len(pts) < 2:
        await update.message.reply_text("❌ Not enough historical data yet.")
        return
    times, temps = zip(*pts)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(times, temps, color='#4fc3f7', linewidth=1.8, marker='o', ms=2)
    ax.fill_between(times, temps, min(temps), alpha=0.2, color='#4fc3f7')
    fig.autofmt_xdate()
    ax.set_ylabel(f"Temperature ({d['units']['temperature']})")
    ax.set_title(f"Last 7 days — {_place(d['location'])}")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120)
    plt.close(fig)
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=f"📈 Last 7 days — {_place(d['location'])}")


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
    try:
        hits = await call(api.geocode, raw, 1)
    except SkyMateError as e:
        await message.reply_text(error_text(e))
        return
    if not hits:
        await message.reply_markdown(f"❌ *{raw}* not found.")
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


# ─── Free-text dispatcher ─────────────────────────────────────────────────────

async def text_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.pop('awaiting', None)
    text = update.message.text.strip()
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
            await update.message.reply_markdown(f"❌ *{text}* not found. Please send another city name:")
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
            id='1', title=f"{_place(d['location'])}: {_num(c['temperature'])}{d['units']['temperature']}",
            description=c['description'].capitalize(),
            input_message_content=InputTextMessageContent(format_current(d), parse_mode='Markdown'))]
    except SkyMateError:
        results = [InlineQueryResultArticle(
            id='0', title=f"'{q}' not found",
            input_message_content=InputTextMessageContent(f"No weather found for '{q}'."))]
    await update.inline_query.answer(results, cache_time=60)


async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error: %s", context.error, exc_info=context.error)


async def restore_subscriptions(app):
    subs = get_all_subscriptions()
    for uid, chat_id, city, units in subs:
        schedule_daily(app.job_queue, uid, chat_id, city, units)
    if subs:
        logger.info("Restored %d subscription(s).", len(subs))


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set in .env")
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(restore_subscriptions).build()

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
                     ("radar", radar_command), ("history", history_command), ("favorites", favorites_command),
                     ("subscribe", subscribe_command), ("cancel", cancel)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_dispatcher))
    app.add_error_handler(error_handler)
    app.run_polling()


if __name__ == '__main__':
    main()
