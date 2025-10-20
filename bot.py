import logging
import requests
import json
import pytz
import time
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto,
    ReplyKeyboardRemove, InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, JobQueue, ConversationHandler,
    InlineQueryHandler
)
from timezonefinder import TimezoneFinder
import matplotlib.pyplot as plt
import io
import numpy as np

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = '8036515444:AAGNbimoj96nsCNpUAp-wRs0A2LQh4WAens'
OPENWEATHER_API_KEY = '0df7dc1b17aae89630b03ee48a0a768c'
CACHE_EXPIRY = 600

cache = {}
DEFAULT_UNITS = 'metric'
WEATHER_EMOJIS = {
    'Clear': '☀️', 'Clouds': '☁️', 'Rain': '🌧️', 'Drizzle': '🌦️',
    'Thunderstorm': '⛈️', 'Snow': '❄️', 'Mist': '🌫️', 'Smoke': '🌫️',
    'Haze': '🌫️', 'Dust': '🌫️', 'Fog': '🌫️', 'Sand': '🌫️',
    'Ash': '🌋', 'Squall': '🌬️', 'Tornado': '🌪️',
}
AQI_DESCRIPTIONS = {
    1: "Good 😊", 2: "Fair 🙂", 3: "Moderate 😐",
    4: "Poor 😷", 5: "Very Poor 🤢"
}
UV_DESCRIPTIONS = {
    0: "Low ☀️", 1: "Low ☀️", 2: "Low ☀️",
    3: "Moderate 🌤️", 4: "Moderate 🌤️", 5: "Moderate 🌤️",
    6: "High ⛱️", 7: "High ⛱️", 8: "Very High 🚫", 
    9: "Very High 🚫", 10: "Extreme ☢️"
}
tf = TimezoneFinder()
STATE_ADD_FAVORITE, STATE_REMOVE_FAVORITE, STATE_SUBSCRIBE = range(3)

def get_cache_key(city: str, units: str) -> str:
    return f"{city.lower()}_{units}"

def is_cache_valid(entry: dict) -> bool:
    return (datetime.now() - entry['timestamp']) < timedelta(minutes=10)

def format_timestamp(ts: int, tz_offset: int) -> str:
    local_time = datetime.utcfromtimestamp(ts + tz_offset)
    return local_time.strftime('%H:%M')

async def get_weather_data(city: str, units: str):
    base_url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        'q': city,
        'appid': OPENWEATHER_API_KEY,
        'units': units,
        'lang': 'en',
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=20) 
        response.raise_for_status()
        data = response.json()
        
        if data.get('cod') != 200:
            logger.error(f"API Error: {data.get('message', 'Unknown error')}")
            return None
            
        return data
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.info(f"City not found: {city}")
        else:
            logger.error(f"Weather API HTTP Error: {str(e)}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Weather API Request Failed: {str(e)}")
    except json.JSONDecodeError:
        logger.error("Invalid JSON response from API")
    except KeyError as e:
        logger.error(f"Missing key in API response: {str(e)}")
        
    return None

async def get_forecast_data(city: str, units: str):
    base_url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {'q': city, 'appid': OPENWEATHER_API_KEY, 'units': units, 'lang': 'en'}
    response = requests.get(base_url, params=params)
    return response.json() if response.status_code == 200 else None

async def get_air_quality(lat: float, lon: float):
    base_url = "http://api.openweathermap.org/data/2.5/air_pollution"
    params = {'lat': lat, 'lon': lon, 'appid': OPENWEATHER_API_KEY}
    response = requests.get(base_url, params=params)
    return response.json() if response.status_code == 200 else None

async def get_uv_index(lat: float, lon: float):
    base_url = "http://api.openweathermap.org/data/2.5/onecall" 
    params = {'lat': lat, 'lon': lon, 'exclude': 'minutely,hourly,daily,alerts', 'appid': OPENWEATHER_API_KEY}
    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        return {'value': response.json().get('current', {}).get('uvi', 0)}
    return None

async def get_historical_weather(lat: float, lon: float, dt: int):
    base_url = "https://api.openweathermap.org/data/2.5/onecall/timemachine"
    params = {'lat': lat, 'lon': lon, 'dt': dt, 'appid': OPENWEATHER_API_KEY, 'units': DEFAULT_UNITS}
    response = requests.get(base_url, params=params)
    return response.json() if response.status_code == 200 else None

async def get_weather_alerts(lat: float, lon: float):
    base_url = "https://api.openweathermap.org/data/2.5/onecall"
    params = {'lat': lat, 'lon': lon, 'exclude': 'current,minutely,hourly,daily', 'appid': OPENWEATHER_API_KEY}
    response = requests.get(base_url, params=params)
    return response.json().get('alerts', []) if response.status_code == 200 else []

async def get_city_suggestions(city: str) -> list:
    url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=5&appid={OPENWEATHER_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return [f"{item['name']}, {item.get('state', '')} {item['country']}".strip() for item in response.json()]
    except Exception as e:
        logger.error(f"City suggestion error: {str(e)}")
    return []

async def generate_weather_map(lat: float, lon: float):
    zoom_level = 10
    x = int((lon + 180) / 360 * (2 ** zoom_level))
    y = int((1 - np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat))) / np.pi) / 2 * (2 ** zoom_level))
    tile_url = f"https://tile.openstreetmap.org/{zoom_level}/{x}/{y}.png"
    
    try:
        response = requests.get(tile_url, timeout=10)
        return response.content if response.status_code == 200 else None
    except requests.exceptions.RequestException as e:
        logger.error(f"Map tile request failed: {str(e)}")
        return None

# --- Formatting Functions ---

async def format_weather_message(data: dict, units: str) -> str:
    main = data.get('main', {})
    weather = data.get('weather', [{}])[0]
    wind = data.get('wind', {})
    
    temp = main.get('temp')
    feels_like = main.get('feels_like')
    humidity = main.get('humidity')
    wind_speed = wind.get('speed')
    description = weather.get('description', '').capitalize()
    emoji = WEATHER_EMOJIS.get(weather.get('main', ''), '')
    
    unit_temp = "°C" if units == "metric" else "°F"
    unit_speed = "m/s" if units == "metric" else "mph"
    
    temp_str = f"{temp}{unit_temp}" if temp is not None else "N/A"
    feels_like_str = f"{feels_like}{unit_temp}" if feels_like is not None else "N/A"
    humidity_str = f"{humidity}%" if humidity is not None else "N/A"
    wind_speed_str = f"{wind_speed}{unit_speed}" if wind_speed is not None else "N/A"
    
    message = (
        f"{emoji} *{data['name']}*\n"
        f"{description}\n\n"
        f"🌡 Temp: {temp_str}\n"
        f"💨 Wind: {wind_speed_str}\n"
        f"💧 Humidity: {humidity_str}\n"
        f"🌡 Feels like: {feels_like_str}"
    )
    return message

async def format_forecast_message(data: dict, units: str) -> str:
    city = data.get('city', {}).get('name', 'Unknown')
    forecasts = data.get('list', [])
    unit_temp = "°C" if units == "metric" else "°F"
    message = f"📅 5-day forecast for *{city}*:\n\n"
    days = {}
    for f in forecasts:
        dt_txt = f['dt_txt']
        date = dt_txt.split(' ')[0]
        if date not in days:
            days[date] = []
        days[date].append(f)
    count = 0
    for date, day_forecasts in days.items():
        if count >= 5:
            break
        
        temps = [f['main']['temp'] for f in day_forecasts if f.get('main', {}).get('temp') is not None]
        if not temps:
            continue
        
        min_temp = min(temps)
        max_temp = max(temps)
        
        noon_forecast = min(day_forecasts, key=lambda x: abs(int(x['dt_txt'][11:13]) - 12))
        
        main_condition = noon_forecast.get('weather', [{}])[0].get('main', '')
        desc = noon_forecast.get('weather', [{}])[0].get('description', '').capitalize()
        emoji = WEATHER_EMOJIS.get(main_condition, '')
        
        try:
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            day_name = date_obj.strftime('%A')
        except ValueError:
            day_name = "Date Unknown"
            
        message += (
            f"*{day_name}* ({date}): {emoji} {desc}\n"
            f"🌡 Min: {min_temp}{unit_temp}, Max: {max_temp}{unit_temp}\n\n"
        )
        count += 1
    return message

async def format_hourly_forecast(data: dict, units: str) -> str:
    forecast_list = data.get('list', [])[:8] 
    message = "⏳ *Next 24 Hours*\n\n"
    unit_temp = "°C" if units == "metric" else "°F"
    
    for f in forecast_list:
        try:
            dt = datetime.fromtimestamp(f['dt'])
            temp = f['main']['temp']
            weather = f['weather'][0]
            emoji = WEATHER_EMOJIS.get(weather['main'], '')
            message += (
                f"{dt.strftime('%H:%M')} {emoji} {weather['description'].capitalize()} "
                f"- {temp}{unit_temp}\n"
            )
        except (KeyError, ValueError):
            continue
            
    return message

async def format_uv_message(uv_data: dict) -> str:
    uv_index = uv_data.get('value', 0)
    try:
        key = int(uv_index)
    except (TypeError, ValueError):
        key = 0
        
    description = UV_DESCRIPTIONS.get(key, "Unknown")
    return f"☀️ UV Index: {uv_index} ({description})"

async def format_aqi_message(aqi_data: dict) -> str:
    try:
        aqi = aqi_data['list'][0]['main']['aqi']
        components = aqi_data['list'][0]['components']
    except (IndexError, KeyError):
        return "AQI data structure is incomplete or malformed."

    desc = AQI_DESCRIPTIONS.get(aqi, "Unknown")
    
    pm2_5 = components.get('pm2_5', 'N/A')
    no2 = components.get('no2', 'N/A')
    so2 = components.get('so2', 'N/A')
    
    return (
        f"🌫️ Air Quality\n"
        f"Index: {aqi} ({desc})\n"
        f"PM2.5: {pm2_5} μg/m³\n"
        f"NO2: {no2} μg/m³\n"
        f"SO2: {so2} μg/m³"
    )

async def format_alerts(alerts: list) -> str:
    if not alerts:
        return "No active weather alerts ⛅"
    message = "🚨 *Weather Alerts*\n\n"
    for alert in alerts:
        event = alert.get('event', 'N/A')
        start_ts = alert.get('start')
        end_ts = alert.get('end')
        description = alert.get('description', 'No details provided.')

        start_time = datetime.fromtimestamp(start_ts) if start_ts else 'Unknown'
        end_time = datetime.fromtimestamp(end_ts) if end_ts else 'Unknown'

        message += (
            f"⚠️ {event}\n"
            f"🕒 {start_time} - {end_time}\n"
            f"{description}\n\n"
        )
    return message

def normalize_city_name(city: str) -> str:
    replacements = {
        'ç': 'c', 'ğ': 'g', 'ı': 'i', 'ö': 'o', 'ş': 's', 'ü': 'u',
        'Ç': 'C', 'Ğ': 'G', 'İ': 'I', 'Ö': 'O', 'Ş': 'S', 'Ü': 'U'
    }
    return ''.join([replacements.get(c, c) for c in city.strip().title()])

# --- Conversation Handler Functions ---

async def add_favorite_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter a city name to add to favorites:")
    return STATE_ADD_FAVORITE

async def add_favorite_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text
    user_data = context.user_data
    user_data.setdefault('favorites', []).append(city)
    await update.message.reply_text(f"Added {city} to favorites!", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def remove_favorite_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    favorites = user_data.get('favorites', [])
    
    if not favorites:
        await update.message.reply_text("No favorites to remove.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    
    keyboard = [[city] for city in favorites]
    await update.message.reply_text(
        "Select a city to remove:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, selective=True)
    )
    return STATE_REMOVE_FAVORITE

async def remove_favorite_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text
    user_data = context.user_data
    try:
        user_data['favorites'].remove(city)
        await update.message.reply_text(f"Removed {city} from favorites!", reply_markup=ReplyKeyboardRemove())
    except ValueError:
        await update.message.reply_text("City not found in favorites.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Command and Handler Logic ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Inline Keyboard for main commands
    inline_keyboard = [
        [InlineKeyboardButton("🌤 Current Weather", switch_inline_query_current_chat='weather_query')],
        [InlineKeyboardButton("📅 Forecast", callback_data='forecast_main'),
         InlineKeyboardButton("⚙ Settings", callback_data='settings')],
        [InlineKeyboardButton("❤ Favorites", callback_data='favorites'),
         InlineKeyboardButton("🚨 Alerts", callback_data='alerts')]
    ]
    inline_markup = InlineKeyboardMarkup(inline_keyboard)

    # Reply Keyboard for location (user friendly on mobile)
    reply_keyboard = [
        [KeyboardButton("📍 Share Current Location", request_location=True)]
    ]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        f"👋 Welcome {update.effective_user.first_name}!\n\n"
        "Please use the button below to share your current location, or choose an option:",
        reply_markup=reply_markup
    )
    
    # Send a separate message for the main command buttons (inline keyboard)
    await update.message.reply_text(
        "⚡ Quick access menu:",
        reply_markup=inline_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "⚡ *Available Commands* ⚡\n\n"
        "/start - Initialize bot\n"
        "/help - Show commands\n"
        "/weather <city> - Current conditions\n"
        "/forecast <city> - 5-day forecast\n"
        "/hourly <city> - 24-hour forecast\n"
        "/radar <city> - Precipitation map\n"
        "/aqi <city> - Air quality info\n"
        "/uv <city> - UV index\n"
        "/alerts <city> - Weather alerts\n"
        "/favorites - Saved locations\n"
        "/subscribe - Daily updates\n"
        "/units - Toggle metric/imperial\n"
        "/history <city> - Past weather data\n"
        "/settings - Configure preferences"
    )
    await update.message.reply_markdown(help_text)

async def units_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    current_units = user_data.get('units', DEFAULT_UNITS)
    new_units = 'imperial' if current_units == 'metric' else 'metric'
    user_data['units'] = new_units
    unit_name = "Imperial (°F)" if new_units == 'imperial' else "Metric (°C)"
    await update.message.reply_text(f"Units switched to: {unit_name}")

async def send_weather_response(update: Update, data: dict, units: str):
    message = await format_weather_message(data, units)
    city_name = data.get('name', 'city')
    coord = data.get('coord', {})
    
    buttons = []
    if coord.get('lat') and coord.get('lon'):
        buttons.append([InlineKeyboardButton("🗺️ Map", callback_data=f'map_{coord["lat"]}_{coord["lon"]}')])
    
    buttons.extend([
        [InlineKeyboardButton("⏰ 24h", callback_data=f'hourly_{city_name}'),
         InlineKeyboardButton("📅 5-day", callback_data=f'forecast_{city_name}')],
        [InlineKeyboardButton("💨 AQI", callback_data=f'aqi_{city_name}')]
    ])
    
    await update.message.reply_markdown(
        message,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message if update.message else update.edited_message
    
    # 1. Determine the raw city name safely
    if context.args:
        raw_city = ' '.join(context.args)
    elif message and message.text:
        raw_city = message.text.strip()
    else:
        logger.warning("Weather command called without arguments or message text.")
        return

    # 2. Safely check for bot mentions/inline query placeholders
    # FIX: Use 'if context.args is None' to handle the case where MessageHandler is triggered
    # and context.args is truly None (though it should be [])
    args_is_empty = not context.args 
    
    if raw_city.startswith('@') and ('weather_query' in raw_city.lower()):
        logger.info(f"Ignoring bot mention/inline query text: {raw_city}")
        return

    # Check for empty input or "Share Current Location" text from ReplyKeyboardMarkup
    if not raw_city or raw_city.startswith('/') or raw_city == "📍 Share Current Location":
        return

    city = normalize_city_name(raw_city)
    
    logger.info(f"Weather request received for: {city}")
    
    units = context.user_data.get('units', DEFAULT_UNITS)
    cache_key = get_cache_key(city, units)
    
    data = None
    if cache_key in cache and time.time() - cache[cache_key]['timestamp'] < CACHE_EXPIRY:
        data = cache[cache_key]['data']
    
    if not data:
        data = await get_weather_data(city, units)
        if not data:
            suggestions = await get_city_suggestions(city)
            error_msg = f"'{raw_city}' not found."
            if suggestions:
                error_msg += "\n\nSimilar cities:\n" + "\n".join(suggestions)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=error_msg,
                reply_markup=ReplyKeyboardRemove() # Remove keyboard after an error
            )
            return
        cache[cache_key] = {'data': data, 'timestamp': time.time()}
    
    await send_weather_response(update, data, units)
    # Ensure the ReplyKeyboardMarkup is removed after a successful command
    await update.message.reply_text("Here is your weather report.", reply_markup=ReplyKeyboardRemove())


async def forecast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = ' '.join(context.args) if context.args else None
    if not city:
        await update.message.reply_text("Please specify a city.")
        return
    
    city = normalize_city_name(city)
    units = context.user_data.get('units', DEFAULT_UNITS)
    data = await get_forecast_data(city, units)
    
    if not data or data.get('cod') != '200':
        await update.message.reply_text(f"Forecast unavailable for {city}.")
        return
    
    forecast_message = await format_forecast_message(data, units)
    await update.message.reply_markdown(forecast_message)

async def hourly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = ' '.join(context.args) if context.args else None
    if not city:
        await update.message.reply_text("Please specify a city.")
        return
    
    city = normalize_city_name(city)
    units = context.user_data.get('units', DEFAULT_UNITS)
    data = await get_forecast_data(city, units)
    
    if not data or data.get('cod') != '200':
        await update.message.reply_text(f"Hourly forecast unavailable for {city}.")
        return
    
    hourly_message = await format_hourly_forecast(data, units)
    await update.message.reply_markdown(hourly_message)

async def aqi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = ' '.join(context.args) if context.args else None
    if not city:
        await update.message.reply_text("Please specify a city.")
        return
    
    city = normalize_city_name(city)
    data = await get_weather_data(city, DEFAULT_UNITS)
    if not data or data.get('cod') != 200 or not data.get('coord'):
        await update.message.reply_text("Location not found.")
        return
    
    coord = data.get('coord')
    aqi_data = await get_air_quality(coord['lat'], coord['lon'])
    
    if not aqi_data or 'list' not in aqi_data:
        await update.message.reply_text("AQI data unavailable.")
        return
    
    aqi_message = await format_aqi_message(aqi_data)
    await update.message.reply_markdown(aqi_message)

async def uv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = ' '.join(context.args) if context.args else None
    if not city:
        await update.message.reply_text("Please specify a city.")
        return
    
    city = normalize_city_name(city)
    data = await get_weather_data(city, DEFAULT_UNITS)
    if not data or data.get('cod') != 200 or not data.get('coord'):
        await update.message.reply_text("Location not found.")
        return
    
    coord = data.get('coord')
    uv_data = await get_uv_index(coord['lat'], coord['lon'])
    
    if not uv_data:
        await update.message.reply_text("UV data unavailable.")
        return
    
    uv_message = await format_uv_message(uv_data)
    await update.message.reply_markdown(uv_message)

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = ' '.join(context.args) if context.args else None
    if not city:
        await update.message.reply_text("Please specify a city.")
        return
    
    city = normalize_city_name(city)
    data = await get_weather_data(city, DEFAULT_UNITS)
    if not data or data.get('cod') != 200 or not data.get('coord'):
        await update.message.reply_text("Location not found.")
        return
    
    coord = data.get('coord')
    alerts = await get_weather_alerts(coord['lat'], coord['lon'])
    alerts_message = await format_alerts(alerts)
    await update.message.reply_markdown(alerts_message)

async def radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = ' '.join(context.args) if context.args else None
    if not city:
        await update.message.reply_text("Please specify a city.")
        return
    
    city = normalize_city_name(city)
    data = await get_weather_data(city, DEFAULT_UNITS)
    if not data or data.get('cod') != 200 or not data.get('coord'):
        await update.message.reply_text("Location not found.")
        return
    
    coord = data.get('coord')
    map_image = await generate_weather_map(coord['lat'], coord['lon'])
    
    if map_image:
        await update.message.reply_photo(photo=map_image, caption="📍 Weather Map")
    else:
        await update.message.reply_text("Map unavailable.")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = ' '.join(context.args) if context.args else None
    if not city:
        await update.message.reply_text("Please specify a city.")
        return
    
    city = normalize_city_name(city)
    data = await get_weather_data(city, DEFAULT_UNITS)
    if not data or data.get('cod') != 200 or not data.get('coord'):
        await update.message.reply_text("Location not found.")
        return
    
    coord = data.get('coord')
    try:
        tz = tf.timezone_at(lat=coord['lat'], lng=coord['lon'])
        if not tz: tz = 'UTC'
        
        now = datetime.now(pytz.timezone(tz))
        target_day = now - timedelta(days=7)
        dt_target = int(target_day.timestamp())
        
        historical_data = await get_historical_weather(coord['lat'], coord['lon'], dt_target)
        
        if not historical_data or 'hourly' not in historical_data:
            await update.message.reply_text("Historical data unavailable for that date.")
            return
        
        hourly_records = historical_data['hourly']
        temps = [h['temp'] for h in hourly_records if 'temp' in h]
        times = [datetime.fromtimestamp(h['dt']).strftime('%H:%M') for h in hourly_records if 'dt' in h]

        if not temps:
            await update.message.reply_text("No temperature data available for plotting.")
            return

        plt.figure(figsize=(10, 5))
        plt.plot(times, temps, marker='o')
        plt.xticks(rotation=45, ha='right')
        plt.xlabel("Time (Hourly)")
        plt.ylabel(f"Temperature (°C)")
        plt.title(f"24-Hour Temperature for {city} ({target_day.strftime('%Y-%m-%d')})")
        plt.grid(True)
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        
        await update.message.reply_photo(photo=buf, caption=f"📈 Historical Data for {city}")
        
    except Exception as e:
        logger.error(f"Historical data error: {str(e)}")
        await update.message.reply_text("Error processing historical data.")


async def weather_by_coords(message_obj, context: ContextTypes.DEFAULT_TYPE, lat: float, lon: float, city_name: str):
    units = context.user_data.get('units', DEFAULT_UNITS)
    
    weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units={units}"
    
    try:
        response = requests.get(weather_url)
        if response.status_code == 200:
            data = response.json()
            data['name'] = city_name
            
            message = await format_weather_message(data, units)
            city_for_buttons = data.get('name', 'city')
            
            buttons = []
            if data.get('coord', {}).get('lat') and data.get('coord', {}).get('lon'):
                buttons.append([InlineKeyboardButton("🗺️ Map", callback_data=f'map_{lat}_{lon}')])
            buttons.extend([
                [InlineKeyboardButton("⏰ 24h", callback_data=f'hourly_{city_for_buttons}'),
                 InlineKeyboardButton("📅 5-day", callback_data=f'forecast_{city_for_buttons}')],
                [InlineKeyboardButton("💨 AQI", callback_data=f'aqi_{city_for_buttons}')]
            ])
            
            # Send the weather report and remove the ReplyKeyboardMarkup (location button)
            await message_obj.reply_markdown(
                message,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            await message_obj.reply_text("Location received.", reply_markup=ReplyKeyboardRemove())


        else:
            await message_obj.reply_text(f"Weather data unavailable: {response.status_code}")
    except Exception as e:
        logger.error(f"Coordinate-based weather error: {str(e)}")
        await message_obj.reply_text("Error fetching weather data.")

async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        location = update.message.location
        lat, lon = location.latitude, location.longitude
        
        reverse_geo_url = f"http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={lon}&limit=1&appid={OPENWEATHER_API_KEY}"
        geo_response = requests.get(reverse_geo_url)
        
        city_name = "Your Location"
        if geo_response.status_code == 200 and geo_response.json():
            city_data = geo_response.json()[0]
            city_name = f"{city_data.get('name', city_data.get('local_names', {}).get('en', 'Unknown'))}, {city_data.get('country', '')}"
            city_name = city_name.strip(', ')

        await weather_by_coords(update.message, context, lat, lon, city_name)

    except Exception as e:
        logger.error(f"Location processing error: {str(e)}")
        await update.message.reply_text("Error processing location data.")

async def favorites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    favorites = user_data.get('favorites', [])
    
    if not favorites:
        keyboard = [[InlineKeyboardButton("➕ Add Favorite", callback_data='add_fav')]] 
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No saved favorites. Add one to see it here.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    keyboard = [
        [InlineKeyboardButton(city, callback_data=f'fav_{city}')]
        for city in favorites
    ]
    keyboard.append([InlineKeyboardButton("➕ Add", callback_data='add_fav'),
                     InlineKeyboardButton("➖ Remove", callback_data='remove_fav')])
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="❤️ Favorite Locations:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def send_daily_update(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = await get_weather_data(job.data['city'], job.data['units'])
    if data:
        message = await format_weather_message(data, job.data['units'])
        await context.bot.send_message(job.chat_id, text=message, parse_mode='Markdown')

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("✅ Subscribe", callback_data='subscribe'),
                 InlineKeyboardButton("❌ Unsubscribe", callback_data='unsubscribe')]]
    await update.message.reply_text(
        "Receive daily weather updates:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id_str = str(query.message.chat_id)
    job_name = f'daily_update_{chat_id_str}'
    
    if query.data == 'subscribe':
        city_to_subscribe = 'London'
        
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()

        context.job_queue.run_repeating(
            send_daily_update,
            interval=86400,
            first=datetime.now(pytz.utc).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1),
            data={'city': city_to_subscribe, 'units': 'metric'},
            chat_id=query.message.chat_id,
            name=job_name
        )
        await query.edit_message_text(f"Subscribed to daily updates for {city_to_subscribe} at 8 AM UTC!")
    else:
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        await query.edit_message_text("Unsubscribed from updates.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == 'favorites':
        # Need to simulate a command update for favorites_command if called from a query
        # Since we cannot create a new Update object easily, we'll route to message.reply_text 
        # to prompt the user to use the command, or adjust favorites_command to accept a query.
        # Sticking to the command pattern for cleaner conversation flow.
        await query.message.reply_text("Please use the /favorites command to manage locations.")
        return

    elif data == 'add_fav':
        await query.message.reply_text("Please use the command /addfavorite to add a new location.")
        return
    elif data == 'remove_fav':
        await query.message.reply_text("Please use the command /removefavorite to delete a location.")
        return
    elif data == 'subscribe' or data == 'unsubscribe':
        await subscribe_callback(update, context)
        return
    elif data == 'forecast_main' or data == 'settings' or data == 'alerts':
        await query.message.reply_text(f"Button '{data}' pressed. Functionality not yet fully implemented.")
        return
    
    if data.startswith('forecast_'):
        city = data.split('_', 1)[1]
        units = context.user_data.get('units', DEFAULT_UNITS)
        forecast_data = await get_forecast_data(city, units)
        if forecast_data and forecast_data.get('cod') == '200':
            message = await format_forecast_message(forecast_data, units)
            await query.edit_message_text(message, parse_mode='Markdown')
        else:
            await query.edit_message_text(f"Forecast unavailable for {city}.")
            
    elif data.startswith('hourly_'):
        city = data.split('_', 1)[1]
        units = context.user_data.get('units', DEFAULT_UNITS)
        forecast_data = await get_forecast_data(city, units)
        if forecast_data and forecast_data.get('cod') == '200':
            message = await format_hourly_forecast(forecast_data, units)
            await query.edit_message_text(message, parse_mode='Markdown')
        else:
            await query.edit_message_text(f"Hourly forecast unavailable for {city}.")
            
    elif data.startswith('aqi_'):
        city = data.split('_', 1)[1]
        weather_data = await get_weather_data(city, DEFAULT_UNITS)
        if weather_data and weather_data.get('cod') == 200 and weather_data.get('coord'):
            coord = weather_data.get('coord')
            aqi_data = await get_air_quality(coord['lat'], coord['lon'])
            if aqi_data and 'list' in aqi_data:
                message = await format_aqi_message(aqi_data)
                await query.edit_message_text(message, parse_mode='Markdown')
            else:
                await query.edit_message_text(f"AQI data unavailable for {city}.")
        else:
            await query.edit_message_text(f"Location data not found for AQI check on {city}.")
            
    elif data.startswith('map_'):
        lat, lon = float(data.split('_')[1]), float(data.split('_')[2])
        map_image = await generate_weather_map(lat, lon)
        if map_image:
            await query.message.reply_photo(photo=map_image, caption="📍 Weather Map")
        else:
            await query.message.reply_text("Map unavailable.")
            
    elif data.startswith('fav_'):
        city = data.split('_', 1)[1]
        units = context.user_data.get('units', DEFAULT_UNITS)
        weather_data = await get_weather_data(city, units)
        if weather_data and weather_data.get('cod') == 200:
            message = await format_weather_message(weather_data, units)
            
            city_name = weather_data.get('name', city)
            coord = weather_data.get('coord', {})
            buttons = []
            if coord.get('lat') and coord.get('lon'):
                buttons.append([InlineKeyboardButton("🗺️ Map", callback_data=f'map_{coord["lat"]}_{coord["lon"]}')])
            buttons.extend([
                [InlineKeyboardButton("⏰ 24h", callback_data=f'hourly_{city_name}'),
                 InlineKeyboardButton("📅 5-day", callback_data=f'forecast_{city_name}')],
                [InlineKeyboardButton("💨 AQI", callback_data=f'aqi_{city_name}')]
            ])
            
            await query.edit_message_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.edit_message_text(f"Weather data for favorite city {city} is unavailable.")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the inline query for current weather."""
    query = update.inline_query.query
    if not query or query == 'weather_query':
        results = [
            InlineQueryResultArticle(
                id=str(time.time()),
                title="Type a City Name",
                input_message_content=InputTextMessageContent(
                    "Please type a city name to get the current weather."
                )
            )
        ]
        await update.inline_query.answer(results)
        return

    city = normalize_city_name(query)
    units = context.user_data.get('units', DEFAULT_UNITS)
    data = await get_weather_data(city, units)
    
    results = []
    if data:
        message_text = await format_weather_message(data, units)
        
        input_content = InputTextMessageContent(
            message_text,
            parse_mode='Markdown'
        )
        
        results.append(
            InlineQueryResultArticle(
                id=str(time.time()),
                title=f"Current Weather in {data['name']}",
                input_message_content=input_content,
                description=data.get('weather', [{}])[0].get('description', '').capitalize(),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Get full report in chat", 
                                          switch_inline_query_current_chat=f"/weather {data['name']}")
                    ]
                ])
            )
        )
    else:
        results.append(
            InlineQueryResultArticle(
                id=str(time.time()),
                title=f"City '{query}' not found",
                input_message_content=InputTextMessageContent(
                    f"Weather for '{query}' could not be retrieved. Try a different city name."
                )
            )
        )
        
    await update.inline_query.answer(results, cache_time=300)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Command not recognized. Use /help for available commands.")

def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # --- Conversation Handlers ---
    conv_fav = ConversationHandler(
        entry_points=[CommandHandler('addfavorite', add_favorite_start)],
        states={
            STATE_ADD_FAVORITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_favorite_end)]
        },
        fallbacks=[]
    )

    conv_remove = ConversationHandler(
        entry_points=[CommandHandler('removefavorite', remove_favorite_start)],
        states={
            STATE_REMOVE_FAVORITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_favorite_end)]
        },
        fallbacks=[MessageHandler(filters.COMMAND, remove_favorite_start)]
    )

    application.add_handler(conv_fav)
    application.add_handler(conv_remove)
    
    # --- Command Handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("units", units_command))
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("forecast", forecast_command))
    application.add_handler(CommandHandler("hourly", hourly_command))
    application.add_handler(CommandHandler("aqi", aqi_command))
    application.add_handler(CommandHandler("uv", uv_command))
    application.add_handler(CommandHandler("alerts", alerts_command))
    application.add_handler(CommandHandler("radar", radar_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("favorites", favorites_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    
    # --- Message Handlers ---
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(InlineQueryHandler(inline_query))
    application.add_handler(MessageHandler(filters.LOCATION, location_handler))
    
    # This handler catches plain text messages and treats them as a city search
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, weather_command))
    
    # Handle unknown commands
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    application.run_polling()

if __name__ == '__main__':
    main()