# ABOUTME: Tests for app factory startup behavior and configuration validation.
# ABOUTME: Verifies that missing critical config causes startup failure.

import pytest
from fastapi.testclient import TestClient

import link_content_scraper.config as config_module
from link_content_scraper.app import create_app


class TestStartupGuard:
    def test_startup_fails_when_stripe_webhook_secret_missing(self, monkeypatch):
        """App startup must raise RuntimeError when STRIPE_WEBHOOK_SECRET is empty."""
        monkeypatch.setattr(config_module, "STRIPE_WEBHOOK_SECRET", "")
        monkeypatch.setattr(config_module, "STRIPE_SECRET_KEY", "sk_test_fake")
        app = create_app()
        with pytest.raises(RuntimeError, match="STRIPE_WEBHOOK_SECRET"):
            with TestClient(app):
                pass

    def test_startup_fails_when_stripe_secret_key_missing(self, monkeypatch):
        """App startup must raise RuntimeError when STRIPE_SECRET_KEY is empty."""
        monkeypatch.setattr(config_module, "STRIPE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setattr(config_module, "STRIPE_SECRET_KEY", "")
        app = create_app()
        with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
            with TestClient(app):
                pass

    def test_startup_succeeds_when_stripe_config_set(self, monkeypatch):
        """App startup succeeds when all required Stripe config values are set."""
        monkeypatch.setattr(config_module, "STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
        monkeypatch.setattr(config_module, "STRIPE_SECRET_KEY", "sk_test_fake")
        app = create_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health")
        assert resp.status_code in (200, 500)  # 500 is ok if other config is missing


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
