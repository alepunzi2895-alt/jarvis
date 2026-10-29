"""Certificati TLS dal trust store di Windows.

Sul PC aziendale il proxy ispeziona il TLS: la CA del proxy sta nello store
Windows, non in certifi. Senza questo, ogni chiamata HTTPS (API Anthropic,
voce, Telegram) fallisce con CERTIFICATE_VERIFY_FAILED e il comando risponde
"Comando non completato". Chiamare una volta, prima dei client HTTP.
"""


def use_system_trust() -> None:
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001 — senza truststore resta il comportamento di prima
        pass
