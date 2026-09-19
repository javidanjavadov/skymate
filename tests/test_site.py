def test_public_pages(client):
    for path in ("/", "/terms", "/privacy", "/robots.txt", "/favicon.svg"):
        assert client.get(path).status_code == 200, path


def test_spa_pages_serve_the_app_with_security_headers(client):
    for path in ("/", "/terms", "/privacy"):
        r = client.get(path)
        assert '<div id="root">' in r.text, path
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"], path
        assert "geolocation=(self)" in r.headers["Permissions-Policy"]


def test_built_assets_are_served(client):
    import re
    html = client.get("/").text
    for asset in re.findall(r'(?:src|href)="(/app/[^"]+)"', html):
        assert client.get(asset).status_code == 200, asset


def test_robots_disallows_console(client):
    assert "Disallow: /console-" in client.get("/robots.txt").text


def test_weather_endpoint_validates_input(client):
    assert client.get("/site/api/weather").status_code == 400
    assert client.get("/site/api/weather", params={"q": "x" * 101}).status_code == 422
    assert client.get("/site/api/weather", params={"lat": 91, "lon": 0}).status_code == 422


def test_site_info_exposes_nothing_sensitive(client):
    info = client.get("/site/api/info").json()
    assert set(info) == {"bot", "premium_stars"}
