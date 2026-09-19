"""Quantities SkyMate derives itself from raw model fields."""
import math
from datetime import datetime, timedelta, timezone


def rh_from_dewpoint(t_c: float, td_c: float) -> float:
    a, b = 17.625, 243.04
    rh = 100 * math.exp(a * td_c / (b + td_c)) / math.exp(a * t_c / (b + t_c))
    return max(0.0, min(100.0, rh))


def dewpoint(t_c: float, rh: float) -> float:
    a, b = 17.625, 243.04
    rh = max(rh, 0.1)
    g = math.log(rh / 100) + a * t_c / (b + t_c)
    return b * g / (a - g)


def feels_like(t_c: float, rh: float, wind_ms: float) -> float:
    """Wind chill below 10 C, heat index above 27 C, otherwise air temperature."""
    wind_kmh = wind_ms * 3.6
    if t_c <= 10 and wind_kmh > 4.8:
        v = wind_kmh ** 0.16
        return 13.12 + 0.6215 * t_c - 11.37 * v + 0.3965 * t_c * v
    if t_c >= 27 and rh >= 40:
        t_f = t_c * 9 / 5 + 32
        hi = (-42.379 + 2.04901523 * t_f + 10.14333127 * rh - 0.22475541 * t_f * rh
              - 6.83783e-3 * t_f ** 2 - 5.481717e-2 * rh ** 2 + 1.22874e-3 * t_f ** 2 * rh
              + 8.5282e-4 * t_f * rh ** 2 - 1.99e-6 * t_f ** 2 * rh ** 2)
        return (hi - 32) * 5 / 9
    return t_c


def wind_dir(u: float, v: float) -> float:
    return (math.degrees(math.atan2(-u, -v)) + 360) % 360


def solar_position(lat: float, lon: float, when: datetime):
    """Returns (zenith_deg, declination_rad, eq_time_min) using the NOAA algorithm."""
    when = when.astimezone(timezone.utc)
    doy = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60 + when.second / 3600
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = hour * 60 + eqt + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cos_z = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    zenith = math.degrees(math.acos(max(-1.0, min(1.0, cos_z))))
    return zenith, decl, eqt


def sun_times(lat: float, lon: float, day: datetime):
    """Sunrise/sunset in UTC for the UTC calendar day of `day`. None during polar day/night."""
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    _, decl, eqt = solar_position(lat, lon, noon)
    la = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl))
              - math.tan(la) * math.tan(decl))
    if cos_ha < -1 or cos_ha > 1:
        return None, None
    ha = math.degrees(math.acos(cos_ha))
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rise = midnight + timedelta(minutes=720 - 4 * (lon + ha) - eqt)
    sset = midnight + timedelta(minutes=720 - 4 * (lon - ha) - eqt)
    return rise, sset


def uv_index(lat: float, lon: float, when: datetime, cloud_pct: float) -> float:
    """Clear-sky UV index from solar zenith angle, attenuated by cloud cover."""
    zenith, _, _ = solar_position(lat, lon, when)
    mu = math.cos(math.radians(zenith))
    if mu <= 0:
        return 0.0
    clear = 12.5 * mu ** 2.42
    c = max(0.0, min(1.0, cloud_pct / 100))
    cloud_factor = 1 - 0.56 * c ** 2.5
    return round(max(0.0, clear * cloud_factor), 1)


def is_day(lat: float, lon: float, when: datetime) -> bool:
    zenith, _, _ = solar_position(lat, lon, when)
    return zenith < 90.833


def condition(t_c, precip_mmh, cloud_pct, vis_m=None, cape=None):
    """Returns (main, description) using the same vocabulary as common weather APIs."""
    p = precip_mmh or 0
    if p >= 0.1:
        if cape is not None and cape >= 1000 and p >= 1:
            return "Thunderstorm", "thunderstorm"
        if t_c is not None and t_c <= 0.5:
            return "Snow", "heavy snow" if p >= 2.5 else "light snow" if p < 0.5 else "snow"
        if p < 0.5:
            return "Drizzle", "light drizzle"
        if p < 2.5:
            return "Rain", "light rain"
        if p < 7.6:
            return "Rain", "moderate rain"
        return "Rain", "heavy rain"
    if vis_m is not None and vis_m < 1000:
        return "Fog", "fog"
    if vis_m is not None and vis_m < 5000:
        return "Mist", "mist"
    c = cloud_pct or 0
    if c < 12:
        return "Clear", "clear sky"
    if c < 37:
        return "Clouds", "few clouds"
    if c < 62:
        return "Clouds", "scattered clouds"
    if c < 88:
        return "Clouds", "broken clouds"
    return "Clouds", "overcast clouds"
