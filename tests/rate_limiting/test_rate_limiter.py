from flask_artisan import RateLimiter


def test_hit_counts_and_window(limiter_app, clock):
    assert RateLimiter.hit("k", 60) == 1
    assert RateLimiter.hit("k", 60) == 2
    assert RateLimiter.attempts("k") == 2
    assert RateLimiter.remaining("k", 5) == 3
    clock.advance(61)
    assert RateLimiter.attempts("k") == 0


def test_too_many_attempts_and_available_in(limiter_app, clock):
    for _ in range(3):
        RateLimiter.hit("k", 60)
    assert RateLimiter.too_many_attempts("k", 3) is True
    assert RateLimiter.too_many_attempts("k", 4) is False
    clock.advance(20)
    assert RateLimiter.available_in("k") == 40
    RateLimiter.clear("k")
    assert RateLimiter.attempts("k") == 0
    assert RateLimiter.available_in("k") == 0


def test_lost_timer_resets(limiter_app):
    for _ in range(3):
        RateLimiter.hit("k", 60)
    limiter_app.make("cache").store().forget("k:timer")
    assert RateLimiter.too_many_attempts("k", 3) is False
    assert RateLimiter.attempts("k") == 0


def test_counter_never_eternal(limiter_app, clock, monkeypatch):
    RateLimiter.hit("k", 60)
    store = limiter_app.make("cache").store()
    original = type(store).increment

    def late_increment(self, key, by=1):
        clock.advance(61)  # la clé expire entre add et increment
        return original(self, key, by)

    monkeypatch.setattr(type(store), "increment", late_increment)
    assert RateLimiter.hit("k", 60) == 1
    monkeypatch.undo()
    clock.advance(61)
    assert RateLimiter.attempts("k") == 0


def test_attempt(limiter_app):
    assert RateLimiter.attempt("k", 2, lambda: "ok") == "ok"
    assert RateLimiter.attempt("k", 2, lambda: None) is True
    assert RateLimiter.attempt("k", 2, lambda: "ok") is False


def test_limiter_store_from_config(limiter_app):
    limiter_app.make("config").set("cache.limiter", "other")
    RateLimiter.hit("k")
    assert limiter_app.make("cache").store("other").get("k") == 1
    assert limiter_app.make("cache").store().get("k") is None
