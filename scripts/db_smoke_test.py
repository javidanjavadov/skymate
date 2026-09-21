"""Exercise every account-data query (bot, API keys, admin panel) against the configured database.

    python scripts/db_smoke_test.py

Uses a throwaway user id and key name and removes them afterwards. Safe to run on production.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skymate_api import admin_panel, auth, db, security, store  # noqa: E402

TEST_UID = 999_000_000_001
TEST_KEY = "smoke-test"


def cleanup():
    """Removes only the throwaway test user and key, including leftovers from an interrupted earlier run."""
    with store.tx("bot") as c:
        for t in ("user_settings", "user_favorites", "user_subscriptions", "premium", "payments", "app_keys",
                  "alert_sent", "users"):
            c.execute(f"DELETE FROM {t} WHERE user_id=?", (TEST_UID,))
    with store.tx("api") as c:
        c.execute("DELETE FROM usage WHERE key_id IN (SELECT id FROM api_keys WHERE name=?)", (TEST_KEY,))
        c.execute("DELETE FROM api_keys WHERE name=?", (TEST_KEY,))


def main():
    print("database:", "postgres" if store.IS_PG else "sqlite")
    db.init()
    store.init("bot")
    security.init_audit()
    import bot

    bot.init_db()
    cleanup()
    try:
        checks(bot)
    finally:
        cleanup()
        print("cleanup ok")
    print("ALL DATABASE CHECKS PASSED")


def checks(bot):

    bot.init_db()
    bot.set_user_units(TEST_UID, "imperial")
    assert bot.get_user_units(TEST_UID) == "imperial"
    bot.add_user_favorite(TEST_UID, "Baku")
    bot.add_user_favorite(TEST_UID, "Baku")
    assert bot.get_user_favorites(TEST_UID) == ["Baku"]
    bot.save_subscription(TEST_UID, TEST_UID, "Baku, AZ", "metric")
    bot.save_subscription(TEST_UID, TEST_UID, "Ganja, AZ", "metric")
    assert bot.get_subscription(TEST_UID)["city"] == "Ganja, AZ"
    bot.grant_premium(TEST_UID, datetime.now(timezone.utc) + timedelta(days=30), "smoke-charge", 150, True)
    assert bot.is_premium(TEST_UID)
    with store.tx("bot") as c:
        c.execute("INSERT INTO users(user_id, username, first_name, last_name, language, first_seen, last_seen, actions) "
                  "VALUES (?,?,?,?,?,?,?,1) ON CONFLICT(user_id) DO UPDATE SET last_seen=excluded.last_seen, "
                  "first_seen=COALESCE(users.first_seen, excluded.first_seen), actions=users.actions+1",
                  (TEST_UID, "smoke", "Smoke", "Test", "en", store.now(), store.now()))
        n = c.execute("INSERT INTO alert_sent(user_id, alert_key, sent_at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                      (TEST_UID, "k", store.now())).rowcount
        n2 = c.execute("INSERT INTO alert_sent(user_id, alert_key, sent_at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                       (TEST_UID, "k", store.now())).rowcount
        assert (n, n2) == (1, 0), (n, n2)
        c.execute("INSERT INTO app_keys(user_id, plan, created_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE "
                  "SET plan=excluded.plan, created_at=excluded.created_at", (TEST_UID, "premium", store.now()))
    print("bot queries ok")

    key = auth.create_key(TEST_KEY, "free")
    for _ in range(3):
        auth.check(key, "/v1/smoke")
    assert any(u["name"] == TEST_KEY and u["requests"] == 3 for u in auth.usage(1))
    kid = [k["id"] for k in auth.list_keys() if k["name"] == TEST_KEY][-1]
    auth.set_plan(kid, "pro")
    print("api key and usage queries ok")

    admin_panel.overview()
    found = admin_panel.users(search="smoke", limit=10, offset=0)["users"]
    assert found and found[0]["premium"], found
    admin_panel.user_detail(TEST_UID)
    admin_panel.grant_premium(TEST_UID, None, 5)
    admin_panel.remove_premium(TEST_UID, None)
    admin_panel.payments(limit=10)
    admin_panel.keys()
    print("admin panel queries ok")


if __name__ == "__main__":
    main()
