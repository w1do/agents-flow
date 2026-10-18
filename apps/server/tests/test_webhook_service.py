"""Регистрация webhook: адрес https без учётных данных и список обновлений для setWebhook."""

import pytest
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.services.webhook import register_webhook, webhook_url


def test_webhook_url_appends_path() -> None:
    assert webhook_url("https://harness.example.com/") == (
        "https://harness.example.com/telegram/webhook"
    )


@pytest.mark.parametrize(
    "public_url",
    [
        None,
        "",
        "http://x",
        "https://user:pw@x",
        "https://x.example/?token=1",
        "https://x.example/#f",
    ],
)
def test_webhook_url_requires_https(public_url: str | None) -> None:
    with pytest.raises(ValueError):
        webhook_url(public_url)


@pytest.mark.asyncio(loop_scope="session")
async def test_register_webhook_passes_allowed_updates() -> None:
    fake = FakeTelegramClient()
    url = "https://harness.example.com/telegram/webhook"

    await register_webhook(fake, url, "s" * 32)

    assert fake.webhooks == [(url, "s" * 32, ("message", "callback_query"))]
