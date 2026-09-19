def test_public_pages(client):
    for path in ("/", "/terms", "/privacy", "/robots.txt", "/assets/site.css", "/assets/site.js"):
        assert client.get(path).status_code == 200, path


def test_pages_have_security_headers(client):
    for path in ("/", "/terms", "/privacy"):
        h = client.get(path).headers
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"], path


def test_robots_disallows_console(client):
    assert "Disallow: /console-" in client.get("/robots.txt").text


def test_demo_validates_input(client):
    assert client.get("/site/api/weather").status_code == 422
    assert client.get("/site/api/weather", params={"q": "x" * 101}).status_code == 422


def test_site_info_exposes_nothing_sensitive(client):
    info = client.get("/site/api/info").json()
    assert set(info) == {"bot", "premium_stars"}
