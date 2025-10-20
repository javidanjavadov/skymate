from telegram import Update
from telegram.ext import ContextTypes
import utils

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! Send me a city name, and I'll tell you the weather.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city_name = update.message.text.strip()
    weather = utils.get_weather_by_city(city_name)
    if weather:
        await update.message.reply_text(weather)
    else:
        await update.message.reply_text("Sorry, I couldn't find weather information for that city.")
