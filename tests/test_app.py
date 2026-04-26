# ABOUTME: Tests for app factory startup behavior and configuration validation.
# ABOUTME: Verifies that missing critical config causes startup failure.

import pytest
from fastapi.testclient import TestClient

import link_content_scraper.config as config_module
from link_content_scraper.app import create_app


def _all_config(monkeypatch):
    """Patch all four required startup env vars."""
    monkeypatch.setattr(config_module, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(config_module, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(config_module, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(config_module, "SUPABASE_KEY", "test_key")


class TestStartupGuard:
    def test_startup_fails_when_stripe_webhook_secret_missing(self, monkeypatch):
        """App startup must raise RuntimeError when STRIPE_WEBHOOK_SECRET is empty."""
        _all_config(monkeypatch)
        monkeypatch.setattr(config_module, "STRIPE_WEBHOOK_SECRET", "")
        app = create_app()
        with pytest.raises(RuntimeError, match="STRIPE_WEBHOOK_SECRET"):
            with TestClient(app):
                pass

    def test_startup_fails_when_stripe_secret_key_missing(self, monkeypatch):
        """App startup must raise RuntimeError when STRIPE_SECRET_KEY is empty."""
        _all_config(monkeypatch)
        monkeypatch.setattr(config_module, "STRIPE_SECRET_KEY", "")
        app = create_app()
        with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
            with TestClient(app):
                pass

    def test_startup_fails_when_supabase_url_missing(self, monkeypatch):
        """App startup must raise RuntimeError when SUPABASE_URL is empty."""
        _all_config(monkeypatch)
        monkeypatch.setattr(config_module, "SUPABASE_URL", "")
        app = create_app()
        with pytest.raises(RuntimeError, match="SUPABASE_URL"):
            with TestClient(app):
                pass

    def test_startup_fails_when_supabase_key_missing(self, monkeypatch):
        """App startup must raise RuntimeError when SUPABASE_KEY is empty."""
        _all_config(monkeypatch)
        monkeypatch.setattr(config_module, "SUPABASE_KEY", "")
        app = create_app()
        with pytest.raises(RuntimeError, match="SUPABASE_KEY"):
            with TestClient(app):
                pass

    def test_startup_succeeds_when_all_config_set(self, monkeypatch):
        """App startup succeeds (no RuntimeError) when all required config values are set."""
        _all_config(monkeypatch)
        app = create_app()
        with TestClient(app):
            pass  # lifespan must not raise


class TestSentryInit:
    def test_sentry_not_initialized_when_dsn_empty(self, monkeypatch):
        """Sentry must not be initialized when SENTRY_DSN is empty."""
        import sentry_sdk
        monkeypatch.setattr(config_module, "STRIPE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setattr(config_module, "STRIPE_SECRET_KEY", "sk_test")
        monkeypatch.setattr(config_module, "SENTRY_DSN", "")
        init_calls = []
        monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: init_calls.append(kwargs))
        create_app()
        assert len(init_calls) == 0

    def test_sentry_initialized_when_dsn_set(self, monkeypatch):
        """Sentry must be initialized with the configured DSN."""
        import sentry_sdk
        monkeypatch.setattr(config_module, "STRIPE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setattr(config_module, "STRIPE_SECRET_KEY", "sk_test")
        monkeypatch.setattr(config_module, "SENTRY_DSN", "https://fake@sentry.io/123")
        init_calls = []
        monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: init_calls.append(kwargs))
        create_app()
        assert len(init_calls) == 1
        assert init_calls[0]["dsn"] == "https://fake@sentry.io/123"

    def test_sentry_init_failure_is_swallowed(self, monkeypatch, caplog):
        """If sentry_sdk.init raises, app startup must continue and log a warning."""
        import logging
        import sentry_sdk

        monkeypatch.setattr(config_module, "STRIPE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setattr(config_module, "STRIPE_SECRET_KEY", "sk_test")
        monkeypatch.setattr(config_module, "SENTRY_DSN", "https://fake@sentry.io/123")

        def _boom(**kwargs):
            raise RuntimeError("sentry init failed")

        monkeypatch.setattr(sentry_sdk, "init", _boom)

        with caplog.at_level(logging.WARNING):
            app = create_app()  # must not raise
        assert app is not None
        assert any("Sentry initialization failed" in m for m in caplog.messages)
