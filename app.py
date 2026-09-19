import customtkinter as ctk
import threading
import json
import os
import io
import logging
from datetime import datetime
from PIL import Image
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import pytz

from skymate_client import SkyMate, SkyMateError

# Change to your public server address before building the .exe for other people.
DEFAULT_API_URL = "http://127.0.0.1:8000"
BOT_USERNAME = "SkyMate bot"

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "SkyMate")
os.makedirs(APP_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


_settings = load_settings()
api = SkyMate(_settings.get("api_url") or DEFAULT_API_URL, _settings.get("api_key", ""))

WEATHER_EMOJIS = {
    'Clear': '☀️', 'Clouds': '☁️', 'Rain': '🌧️', 'Drizzle': '🌦️', 'Thunderstorm': '⛈️',
    'Snow': '❄️', 'Mist': '🌫️', 'Fog': '🌫️',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

FAVORITES_FILE = os.path.join(APP_DIR, "favorites.json")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG_DARK = "#1e1e2e"
BG_CARD = "#2a2a3e"
ACCENT = "#4fc3f7"
TEXT_DIM = "#9999aa"


class SkyMateApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SkyMate")
        self.geometry("960x660")
        self.minsize(720, 520)
        self.configure(fg_color=BG_DARK)

        self.units = "metric"
        self.current_city = None
        self._hourly_canvas = None
        self.favorites = self._load_favorites()
        self.plan = None
        self.max_days = 5

        self._build_ui()
        self.after(300, self._check_account)

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_favorites(self):
        if os.path.exists(FAVORITES_FILE):
            try:
                with open(FAVORITES_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_favorites(self):
        with open(FAVORITES_FILE, "w") as f:
            json.dump(self.favorites, f)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_body()

    def _build_header(self):
        hdr = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color=BG_CARD)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="🌤  SkyMate",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=ACCENT
        ).pack(side="left", padx=16)

        self._units_btn = ctk.CTkButton(
            hdr, text="°C / °F", width=72, height=32,
            fg_color="transparent", border_width=1, border_color=ACCENT,
            text_color=ACCENT, hover_color=BG_DARK,
            command=self._toggle_units
        )
        self._units_btn.pack(side="right", padx=(4, 16))

        ctk.CTkButton(
            hdr, text="⚙", width=36, height=32, fg_color="transparent", border_width=1,
            border_color=TEXT_DIM, hover_color=BG_DARK, command=self._open_settings
        ).pack(side="right", padx=4)

        self._plan_lbl = ctk.CTkLabel(hdr, text="", text_color=TEXT_DIM, font=ctk.CTkFont(size=12))
        self._plan_lbl.pack(side="left", padx=4)

        search_btn = ctk.CTkButton(
            hdr, text="Search", width=80, height=32,
            command=self._on_search
        )
        search_btn.pack(side="right", padx=4)

        self._search_var = ctk.StringVar()
        self._search_entry = ctk.CTkEntry(
            hdr, textvariable=self._search_var,
            placeholder_text="Search city…", width=280, height=32
        )
        self._search_entry.pack(side="right", padx=4)
        self._search_entry.bind("<Return>", lambda _: self._on_search())

    def _build_body(self):
        body = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=6, pady=6)

        self._build_sidebar(body)
        self._build_content(body)

    def _build_sidebar(self, parent):
        sidebar = ctk.CTkFrame(parent, width=170, fg_color=BG_CARD, corner_radius=10)
        sidebar.pack(side="left", fill="y", padx=(0, 6))
        sidebar.pack_propagate(False)

        ctk.CTkLabel(
            sidebar, text="Favorites",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(padx=10, pady=(12, 4))

        self._fav_scroll = ctk.CTkScrollableFrame(
            sidebar, fg_color="transparent", corner_radius=0
        )
        self._fav_scroll.pack(fill="both", expand=True, padx=4)

        ctk.CTkButton(
            sidebar, text="+ Add City", height=28,
            fg_color="transparent", border_width=1,
            command=self._add_fav_dialog
        ).pack(padx=10, pady=10, fill="x")

        self._refresh_fav_list()

    def _build_content(self, parent):
        content = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10)
        content.pack(side="left", fill="both", expand=True)

        self._tabs = ctk.CTkTabview(content, fg_color=BG_DARK)
        self._tabs.pack(fill="both", expand=True, padx=8, pady=8)

        self._tab_current = self._tabs.add("Current")
        self._tab_forecast = self._tabs.add("5-Day")
        self._tab_hourly = self._tabs.add("Hourly")
        self._tab_aqi = self._tabs.add("AQI / UV")
        self._tab_map = self._tabs.add("Map")

        self._build_tab_current()
        self._build_tab_forecast()
        self._build_tab_hourly()
        self._build_tab_aqi()
        self._build_tab_map()

        self._show_welcome()

    def _build_tab_current(self):
        scroll = ctk.CTkScrollableFrame(self._tab_current, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        self._lbl_city = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=22, weight="bold"))
        self._lbl_city.pack(pady=(20, 2))

        self._lbl_desc = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=13), text_color=TEXT_DIM)
        self._lbl_desc.pack(pady=2)

        self._lbl_temp = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=64, weight="bold"), text_color=ACCENT)
        self._lbl_temp.pack(pady=8)

        details = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=10)
        details.pack(padx=30, pady=6, fill="x")
        details.columnconfigure((0, 1), weight=1)

        self._detail_labels = {}
        fields = [
            ("feels", 0, 0), ("wind", 0, 1),
            ("humidity", 1, 0), ("pressure", 1, 1),
            ("sunrise", 2, 0), ("sunset", 2, 1),
        ]
        for key, row, col in fields:
            lbl = ctk.CTkLabel(details, text="", font=ctk.CTkFont(size=13))
            lbl.grid(row=row, column=col, padx=16, pady=8, sticky="w")
            self._detail_labels[key] = lbl

        self._lbl_alerts = ctk.CTkLabel(
            scroll, text="", wraplength=480, text_color="orange",
            font=ctk.CTkFont(size=12)
        )
        self._lbl_alerts.pack(pady=4)

    def _build_tab_forecast(self):
        self._forecast_scroll = ctk.CTkScrollableFrame(self._tab_forecast, fg_color="transparent")
        self._forecast_scroll.pack(fill="both", expand=True)
        self._forecast_rows = []

    def _build_tab_hourly(self):
        self._hourly_frame = ctk.CTkFrame(self._tab_hourly, fg_color="transparent")
        self._hourly_frame.pack(fill="both", expand=True)

    def _build_tab_aqi(self):
        scroll = ctk.CTkScrollableFrame(self._tab_aqi, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        self._aqi_labels = {}
        for key in ("index", "pm25", "no2", "so2", "co", "o3", "uv"):
            lbl = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=14))
            lbl.pack(pady=6)
            self._aqi_labels[key] = lbl

    def _build_tab_map(self):
        self._map_frame = ctk.CTkFrame(self._tab_map, fg_color="transparent")
        self._map_frame.pack(fill="both", expand=True)
        ctk.CTkLabel(self._map_frame, text="Search a city to view its map", text_color=TEXT_DIM).pack(expand=True)

    # ── Account / settings ────────────────────────────────────────────────────

    def _check_account(self):
        if not api.key:
            self._lbl_desc.configure(text="Click ⚙ and paste your key. Get it in Telegram: send /app to "
                                          f"the {BOT_USERNAME}.", text_color=TEXT_DIM)
            self._plan_lbl.configure(text="not connected")
            self._open_settings()
            return
        threading.Thread(target=self._load_plan, daemon=True).start()

    def _load_plan(self):
        try:
            me = api.me()
        except SkyMateError as e:
            text = "invalid key: click ⚙" if e.status == 401 else "server offline"
            self.after(0, lambda: self._plan_lbl.configure(text=text, text_color="orange"))
            return
        self.plan = me["plan"]
        self.max_days = me["limits"].get("max_forecast_days") or 10
        premium = self.plan not in ("free", "app_free")
        label = "⭐ Premium" if premium else "Free: /premium in Telegram for 10-day forecasts"
        self.after(0, lambda: self._plan_lbl.configure(text=label, text_color=ACCENT if premium else TEXT_DIM))

    def _open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("SkyMate settings")
        win.geometry("460x250")
        win.configure(fg_color=BG_DARK)
        win.transient(self)
        win.after(100, win.grab_set)
        ctk.CTkLabel(win, text="Your key (send /app to the SkyMate Telegram bot to get one)").pack(
            anchor="w", padx=16, pady=(16, 2))
        key_var = ctk.StringVar(value=api.key)
        ctk.CTkEntry(win, textvariable=key_var, width=420, show="•").pack(padx=16)
        ctk.CTkLabel(win, text="Server address").pack(anchor="w", padx=16, pady=(12, 2))
        url_var = ctk.StringVar(value=api.base)
        ctk.CTkEntry(win, textvariable=url_var, width=420).pack(padx=16)

        def save():
            url = url_var.get().strip() or DEFAULT_API_URL
            key = key_var.get().strip()
            api.configure(url, key)
            save_settings({"api_url": url, "api_key": key})
            win.destroy()
            self._plan_lbl.configure(text="checking…", text_color=TEXT_DIM)
            threading.Thread(target=self._load_plan, daemon=True).start()
            if self.current_city:
                self._fetch_city(self.current_city)

        ctk.CTkButton(win, text="Save", command=save).pack(pady=16)

    # ── Welcome / loading states ──────────────────────────────────────────────

    def _show_welcome(self):
        self._lbl_city.configure(text="Welcome to SkyMate 🌤")
        self._lbl_desc.configure(text="Search for a city to get started", text_color=TEXT_DIM)
        self._lbl_temp.configure(text="")
        for lbl in self._detail_labels.values():
            lbl.configure(text="")
        self._lbl_alerts.configure(text="")

    def _show_loading(self):
        self._lbl_city.configure(text="Loading…", text_color=TEXT_DIM)
        self._lbl_desc.configure(text="")
        self._lbl_temp.configure(text="")

    # ── Search ────────────────────────────────────────────────────────────────

    def _on_search(self):
        city = self._search_var.get().strip()
        if city:
            self._fetch_city(city)

    def _fetch_city(self, city: str):
        self._tabs.set("Current")
        self._show_loading()
        threading.Thread(target=self._worker, args=(city,), daemon=True).start()

    def _worker(self, city: str):
        def fail(title, detail=""):
            self.after(0, lambda: self._lbl_city.configure(text=title, text_color="red"))
            self.after(0, lambda: self._lbl_desc.configure(text=detail, text_color=TEXT_DIM))
            self.after(0, lambda: self._lbl_temp.configure(text=""))

        try:
            now = api.current(q=city, units=self.units)
        except SkyMateError as e:
            if e.status == 404:
                fail(f"City '{city}' not found", "Check the spelling or try 'City, CC' (e.g. Paris, FR)")
            elif e.status == 401:
                fail("Key missing or invalid", "Click ⚙ and paste the key from /app in the Telegram bot")
            elif e.status == 429:
                fail("Daily limit reached", "Your plan's daily request limit is used up. Premium raises it.")
            else:
                fail("Weather service unavailable", e.message)
            return

        self.current_city = city
        loc = now["location"]
        lat, lon = loc["lat"], loc["lon"]

        def safe(fn, *a, **kw):
            try:
                return fn(*a, **kw)
            except SkyMateError:
                return None

        daily = safe(api.daily, lat=lat, lon=lon, days=self.max_days, units=self.units)
        hourly = safe(api.hourly, lat=lat, lon=lon, hours=24, units=self.units)
        aq = safe(api.air_quality, lat=lat, lon=lon)
        alerts = safe(api.alerts, lat=lat, lon=lon, units=self.units)
        tile = safe(api.map_png, lat=lat, lon=lon)

        self.after(0, lambda: self._render_current(now, alerts))
        self.after(0, lambda: self._render_forecast(daily))
        self.after(0, lambda: self._render_hourly(hourly))
        self.after(0, lambda: self._render_aqi(aq, now["current"]["uv_index"]))
        self.after(0, lambda: self._render_map(tile))

    # ── Renderers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _local(iso: str, loc: dict) -> datetime:
        return datetime.fromisoformat(iso).astimezone(pytz.timezone(loc["timezone"]))

    def _render_current(self, d: dict, alerts: dict | None):
        loc, c, u = d["location"], d["current"], d["units"]
        emoji = WEATHER_EMOJIS.get(c["condition"], "🌡")
        self._lbl_city.configure(text=f"{emoji}  {loc['name']}, {loc['country']}", text_color="white")
        desc = c["description"].capitalize()
        if d["meta"].get("stale"):
            desc += f"   (offline mode: forecast from {round(d['meta']['data_age_hours'])} h ago)"
        self._lbl_desc.configure(text=desc, text_color=TEXT_DIM)
        t = u["temperature"]
        self._lbl_temp.configure(text=f"{round(c['temperature'])}{t}" if c["temperature"] is not None else "N/A")
        fmt = lambda v, s="": "N/A" if v is None else f"{round(v)}{s}"
        self._detail_labels["feels"].configure(text=f"🌡 Feels like: {fmt(c['feels_like'], t)}")
        self._detail_labels["wind"].configure(text=f"💨 Wind: {c['wind_speed']} {u['speed']}")
        self._detail_labels["humidity"].configure(text=f"💧 Humidity: {fmt(c['humidity'], '%')}")
        self._detail_labels["pressure"].configure(text=f"🔵 Pressure: {fmt(c['pressure'], ' hPa')}")
        sun = d.get("sun", {})
        self._detail_labels["sunrise"].configure(
            text=f"🌅 Sunrise: {self._local(sun['sunrise'], loc):%H:%M}" if sun.get("sunrise") else "")
        self._detail_labels["sunset"].configure(
            text=f"🌇 Sunset: {self._local(sun['sunset'], loc):%H:%M}" if sun.get("sunset") else "")
        if alerts and alerts["alerts"]:
            self._lbl_alerts.configure(text="🚨 " + ", ".join(a["event"] for a in alerts["alerts"][:3]))
        else:
            self._lbl_alerts.configure(text="")

    def _render_forecast(self, data: dict | None):
        for w in self._forecast_rows:
            w.destroy()
        self._forecast_rows.clear()
        if not data or not data["daily"]:
            lbl = ctk.CTkLabel(self._forecast_scroll, text="Forecast unavailable", text_color=TEXT_DIM)
            lbl.pack(pady=20)
            self._forecast_rows.append(lbl)
            return
        unit_t = data["units"]["temperature"]
        for day in data["daily"]:
            date = datetime.fromisoformat(day["date"])
            emoji = WEATHER_EMOJIS.get(day["condition"], "🌡")
            row = ctk.CTkFrame(self._forecast_scroll, fg_color=BG_CARD, corner_radius=8)
            row.pack(fill="x", padx=8, pady=4)
            ctk.CTkLabel(row, text=f"{emoji}  {date:%A}", font=ctk.CTkFont(size=13, weight="bold"),
                         width=160, anchor="w").pack(side="left", padx=12, pady=10)
            ctk.CTkLabel(row, text=day["description"].capitalize(), text_color=TEXT_DIM, width=160,
                         anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"↓ {round(day['temp_min'])}{unit_t}   ↑ {round(day['temp_max'])}{unit_t}",
                         font=ctk.CTkFont(size=13), text_color=ACCENT).pack(side="right", padx=14)
            self._forecast_rows.append(row)

    def _render_hourly(self, data: dict | None):
        if self._hourly_canvas:
            self._hourly_canvas.get_tk_widget().destroy()
            self._hourly_canvas = None
        for w in self._hourly_frame.winfo_children():
            w.destroy()
        if not data or not data["hourly"]:
            ctk.CTkLabel(self._hourly_frame, text="Hourly data unavailable", text_color=TEXT_DIM).pack(expand=True)
            return
        loc = data["location"]
        items = [h for h in data["hourly"] if h["temperature"] is not None]
        times = [self._local(h["time"], loc).strftime("%H:%M") for h in items]
        temps = [round(h["temperature"]) for h in items]
        unit_t = data["units"]["temperature"]

        fig, ax = plt.subplots(figsize=(6.5, 3.2))
        fig.patch.set_facecolor("#1e1e2e")
        ax.set_facecolor("#2a2a3e")
        ax.plot(times, temps, marker="o", color=ACCENT, linewidth=2, markersize=6)
        ax.fill_between(range(len(temps)), temps, min(temps), alpha=0.15, color=ACCENT)
        for spine in ax.spines.values():
            spine.set_edgecolor("#444")
        ax.tick_params(colors="white", rotation=30)
        ax.set_ylabel(f"Temp ({unit_t})", color="white", fontsize=10)
        ax.set_title("Next 24 Hours (local time)", color="white", fontsize=12)
        ax.grid(True, alpha=0.2, color="gray")
        plt.tight_layout()
        self._hourly_canvas = FigureCanvasTkAgg(fig, self._hourly_frame)
        self._hourly_canvas.draw()
        self._hourly_canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        plt.close(fig)

    def _render_aqi(self, data: dict | None, uv_val):
        keys = ("pm25", "no2", "so2", "co", "o3")
        if data:
            aq = data["air_quality"]
            comp = aq["components"]
            idx = aq.get("european_aqi")
            head = f"🌫️  European AQI: {idx}" if idx is not None else f"🌫️  AQI: {aq.get('index_1_5')} / 5"
            self._aqi_labels["index"].configure(text=head)
            names = {"pm25": ("PM2.5", "pm2_5"), "no2": ("NO₂", "no2"), "so2": ("SO₂", "so2"),
                     "co": ("CO", "co"), "o3": ("O₃", "o3")}
            for k in keys:
                label, field = names[k]
                v = comp.get(field)
                self._aqi_labels[k].configure(text=f"{label}:  {'N/A' if v is None else round(v, 1)} μg/m³")
        else:
            self._aqi_labels["index"].configure(text="Air quality data unavailable")
            for k in keys:
                self._aqi_labels[k].configure(text="")
        self._aqi_labels["uv"].configure(text=f"☀️  UV Index: {uv_val}")

    def _render_map(self, png: bytes | None):
        for w in self._map_frame.winfo_children():
            w.destroy()
        if not png:
            ctk.CTkLabel(self._map_frame, text="Map available after the first forecast download",
                         text_color=TEXT_DIM).pack(expand=True)
            return
        img = Image.open(io.BytesIO(png))
        w, h = img.size
        scale = min(620 / w, 460 / h)
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(int(w * scale), int(h * scale)))
        lbl = ctk.CTkLabel(self._map_frame, image=ctk_img, text="")
        lbl.pack(expand=True, pady=10)
        lbl._image_ref = ctk_img

    # ── Favorites ─────────────────────────────────────────────────────────────

    def _refresh_fav_list(self):
        for w in self._fav_scroll.winfo_children():
            w.destroy()

        for city in self.favorites:
            row = ctk.CTkFrame(self._fav_scroll, fg_color="transparent")
            row.pack(fill="x", pady=1)

            ctk.CTkButton(
                row, text=city, anchor="w", height=28,
                fg_color="transparent", hover_color=("#d0d0d0", "#333344"),
                command=lambda c=city: self._fetch_city(c)
            ).pack(side="left", fill="x", expand=True)

            ctk.CTkButton(
                row, text="✕", width=24, height=24,
                fg_color="transparent", hover_color="red", text_color=TEXT_DIM,
                command=lambda c=city: self._remove_fav(c)
            ).pack(side="right")

    def _add_fav_dialog(self):
        dlg = ctk.CTkInputDialog(text="Enter city name:", title="Add Favorite")
        city = dlg.get_input()
        if city and city.strip() and city.strip() not in self.favorites:
            self.favorites.append(city.strip())
            self._save_favorites()
            self._refresh_fav_list()

    def _remove_fav(self, city: str):
        if city in self.favorites:
            self.favorites.remove(city)
            self._save_favorites()
            self._refresh_fav_list()

    # ── Units toggle ──────────────────────────────────────────────────────────

    def _toggle_units(self):
        self.units = "imperial" if self.units == "metric" else "metric"
        self._units_btn.configure(text="°F / °C" if self.units == "imperial" else "°C / °F")
        if self.current_city:
            self._fetch_city(self.current_city)


if __name__ == "__main__":
    app = SkyMateApp()
    app.mainloop()
