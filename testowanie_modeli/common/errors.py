"""Wyjątki wspólne dla ekstrakcji i benchmarku (bez zależności od numpy)."""


class Unavailable(Exception):
    """Wejście nie nadaje się do analizy - powód trafia do Feature.reason."""
