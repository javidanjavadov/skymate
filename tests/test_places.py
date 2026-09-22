from skymate_api import places, site


class FakeResponse:
    def __init__(self, address):
        self._address = address

    def raise_for_status(self):
        pass

    def json(self):
        return {"address": self._address}


def test_label_prefers_neighbourhood_and_city():
    assert places._label({"village": "Ahmedli", "city": "Baku"}) == "Ahmedli, Baku"
    assert places._label({"suburb": "Camden Town", "city": "London"}) == "Camden Town, London"
    assert places._label({"town": "Quba"}) == "Quba"


def test_lookup_is_cached_and_identifies_skymate(monkeypatch):
    places.init()
    calls = []

    def fake_get(url, **kw):
        calls.append(kw)
        return FakeResponse({"village": "Ahmedli", "city": "Baku", "country_code": "az"})

    monkeypatch.setattr(places.requests, "get", fake_get)
    monkeypatch.setattr(places, "_last_request", 0.0)
    first = places.lookup(40.37561, 49.95682)
    second = places.lookup(40.37564, 49.95679)  # same ~100 m square
    assert first == second == {"name": "Ahmedli, Baku", "country": "AZ"}
    assert len(calls) == 1
    assert calls[0]["headers"]["User-Agent"].startswith("SkyMate/")
    assert calls[0]["params"]["lat"] == "40.376"  # only the rounded position leaves SkyMate


def test_failed_lookup_is_not_cached(monkeypatch):
    places.init()

    def broken(url, **kw):
        raise places.requests.ConnectionError("offline")

    monkeypatch.setattr(places.requests, "get", broken)
    monkeypatch.setattr(places, "_last_request", 0.0)
    assert places.lookup(10.123, 20.456) is None
    monkeypatch.setattr(places.requests, "get", lambda url, **kw: FakeResponse({"town": "Later"}))
    assert places.lookup(10.123, 20.456) == {"name": "Later", "country": ""}


def test_only_the_visitors_own_position_is_looked_up(monkeypatch):
    """Search results and city names never reach OpenStreetMap; only precise=1 with coordinates does."""
    called = []

    class Stop(Exception):
        pass

    def current(loc):
        raise Stop(loc["name"])

    monkeypatch.setattr(places, "lookup", lambda lat, lon: called.append((lat, lon)) or {"name": "Ahmedli, Baku", "country": "AZ"})
    monkeypatch.setattr(site.forecast, "resolve_location",
                        lambda q, lat, lon: {"name": "Baku", "country": "AZ", "lat": lat or 40.4, "lon": lon or 49.9})
    monkeypatch.setattr(site.forecast, "current", current)

    def shown(q, lat, lon, precise):
        try:
            site._dashboard(q, lat, lon, precise)
        except Stop as e:
            return str(e)

    assert shown(None, 40.4, 49.9, False) == "Baku"      # a city picked from search
    assert shown("Baku", None, None, True) == "Baku"     # a typed city name
    assert called == []
    assert shown(None, 40.3756, 49.9568, True) == "Ahmedli, Baku"
    assert called == [(40.3756, 49.9568)]
