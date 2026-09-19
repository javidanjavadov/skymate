from datetime import datetime, timezone

from skymate_api import observations, physics
from skymate_api.server import _convert


def test_metar_basic():
    ref = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
    r = observations.parse_metar("UBBB 190930Z 36018KT 9999 SCT027 26/18 Q1014 NOSIG", ref=ref)
    assert r["station_id"] == "UBBB"
    assert r["temperature"] == 26 and r["dew_point"] == 18
    assert r["wind_direction"] == 360 and r["wind_speed"] == round(18 * 0.514444, 1)
    assert r["pressure"] == 1014 and r["visibility"] == 10000 and r["cloud_cover"] == 44


def test_metar_negative_us_units_and_weather():
    ref = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    r = observations.parse_metar("KJFK 051151Z 31015G25KT 3/4SM -SN BKN008 M02/M05 A2992 RMK T10221050", ref=ref)
    assert r["temperature"] == -2.2 and r["dew_point"] == -5.0
    assert r["wind_gust"] == round(25 * 0.514444, 1)
    assert r["pressure"] == round(29.92 * 33.8639, 1)
    assert r["weather"] == "light snow"


def test_synop():
    line = "37575,2026,09,19,09,00,AAXX 19091 37575 42697 82701 10223 20149 39633 40188 52001 885//="
    r = observations.parse_synop(line)
    assert r["station_id"] == "37575"
    assert r["temperature"] == 22.3 and r["dew_point"] == 14.9
    assert r["pressure"] == 1018.8
    assert r["cloud_cover"] == 100 and r["wind_direction"] == 270


def test_synop_nil_is_ignored():
    assert observations.parse_synop("37575,2026,09,19,09,00,AAXX 19091 37575 NIL=") is None


def test_physics():
    assert abs(physics.rh_from_dewpoint(20, 20) - 100) < 0.01
    assert physics.feels_like(-5, 50, 10) < -5
    assert physics.condition(20, 5, 90)[0] == "Rain"
    assert physics.condition(-3, 1, 90)[0] == "Snow"


def test_imperial_conversion():
    out = _convert({"temperature": 0, "wind_speed": 10, "precipitation_sum": 25.4, "visibility": 1609.34}, "imperial")
    assert out == {"temperature": 32.0, "wind_speed": 22.4, "precipitation_sum": 1.0, "visibility": 1.0}
