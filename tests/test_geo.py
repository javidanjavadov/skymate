from skymate_api import db, geo

# (id, name, ascii, alt, country, admin1, lat, lon, population, timezone)
PLACES = [
    (1, "Baku", "baku", ",baku,", "AZ", "09", 40.37767, 49.89201, 2_351_300, "Asia/Baku"),
    (2, "Qaraçuxur", "qaracuxur", ",qaracuxur,", "AZ", "09", 40.39667, 49.97361, 87_349, "Asia/Baku"),
    (3, "Mardakan", "mardakan", ",mardakan,", "AZ", "09", 40.49194, 50.14222, 15_267, "Asia/Baku"),
    (4, "Sumgayit", "sumgayit", ",sumgayit,", "AZ", "43", 40.58972, 49.66861, 341_100, "Asia/Baku"),
]


def setup_module():
    db.init()
    with db.tx() as c:
        c.executemany("INSERT OR REPLACE INTO cities VALUES (?,?,?,?,?,?,?,?,?,?)", PLACES)


def test_district_of_a_big_city_reports_the_city():
    # Khatai, Baku: Qaraçuxur's point is nearer, but it is a settlement inside Baku
    assert geo.reverse(40.3756, 49.9568)["name"] == "Baku"


def test_places_outside_the_urban_area_keep_their_name():
    assert geo.reverse(40.4919, 50.1422)["name"] == "Mardakan"
    assert geo.reverse(40.5897, 49.6686)["name"] == "Sumgayit"  # its own region, never merged into Baku
