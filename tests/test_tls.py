import ssl

from core import tls


def test_use_system_trust_is_safe_to_call_twice():
    original = ssl.SSLContext
    try:
        tls.use_system_trust()
        tls.use_system_trust()
    finally:
        ssl.SSLContext = original  # inject_into_ssl patcha il modulo ssl: ripristina per gli altri test


def test_use_system_trust_never_raises_without_truststore(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "truststore":
            raise ImportError("assente")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    tls.use_system_trust()
