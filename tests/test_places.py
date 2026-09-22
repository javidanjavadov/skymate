from skymate_api import places, site


class FakeResponse:
    def __init__(self, address):
        self._address = address

    def raise_for_status(self):
        pass

    def json(self):
        return {"address": self._address}


def test_neighbourhood_ignores_unusable_names():
    # The city name always comes from SkyMate's own data, so only the smaller part is taken from the map service
    assert places._neighbourhood({"village": "Ahmedli", "city": "Sabail Raion"}, "Baku") == "Ahmedli"
    assert places._neighbourhood({"suburb": "Chalk Farm", "city": "Greater London"}, "London") == "Chalk Farm"
    assert places._neighbourhood({"neighbourhood": "Manhattan Community Board 5", "suburb": "Manhattan"}, "New York City") == "Manhattan"
    assert places._neighbourhood({"quarter": "Shibuya"}, "Shibuya") == ""  # would just repeat the city
    assert places._neighbourhood({"county": "Quba District"}, "Quba") == ""  # no neighbourhood: the city name stays


def test_lookup_is_cached_and_identifies_skymate(monkeypatch):
    places.init()
    calls = []

    def fake_get(url, **kw):
        calls.append(kw)
        return FakeResponse({"road": "Vung Tau Street", "village": "Ahmedli", "postcode": "1126", "country_code": "az"})

    monkeypatch.setattr(places.requests, "get", fake_get)
    monkeypatch.setattr(places, "_last_request", 0.0)
    first = places.lookup(40.375612, 49.956821, "Baku")
    second = places.lookup(40.375588, 49.956799, "Baku")  # same ~10 m square
    assert first == second == {"name": "Vung Tau Street, Ahmedli, Baku", "country": "AZ", "detail": ""}
    assert len(calls) == 1
    assert calls[0]["headers"]["User-Agent"].startswith("SkyMate/")
    assert calls[0]["params"]["lat"] == "40.3756"  # only the rounded position leaves SkyMate


def test_failed_lookup_is_not_cached(monkeypatch):
    places.init()

    def broken(url, **kw):
        raise places.requests.ConnectionError("offline")

    monkeypatch.setattr(places.requests, "get", broken)
    monkeypatch.setattr(places, "_last_request", 0.0)
    assert places.lookup(10.123, 20.456, "Somewhere") is None
    monkeypatch.setattr(places.requests, "get", lambda url, **kw: FakeResponse({"suburb": "Later"}))
    assert places.lookup(10.123, 20.456, "Somewhere")["name"] == "Later, Somewhere"  # no street mapped there


def test_only_the_visitors_own_position_is_looked_up(monkeypatch):
    """Search results and typed city names never reach the map service; only precise=1 with coordinates does."""
    called = []

    class Stop(Exception):
        pass

    monkeypatch.setattr(places, "lookup",
                        lambda lat, lon, city: called.append((lat, lon, city)) or {"name": "Ahmedli, Baku", "country": "AZ"})
    monkeypatch.setattr(site.forecast, "resolve_location",
                        lambda q, lat, lon: {"name": "Baku", "country": "AZ", "lat": lat or 40.4, "lon": lon or 49.9})
    monkeypatch.setattr(site.forecast, "current", lambda loc: (_ for _ in ()).throw(Stop(loc["name"])))

    def shown(q, lat, lon, precise):
        try:
            site._dashboard(q, lat, lon, precise)
        except Stop as e:
            return str(e)

    assert shown(None, 40.4, 49.9, False) == "Baku"      # a city picked from search
    assert shown("Baku", None, None, True) == "Baku"     # a typed city name
    assert called == []
    assert shown(None, 40.3756, 49.9568, True) == "Ahmedli, Baku"
    assert called == [(40.3756, 49.9568, "Baku")]
