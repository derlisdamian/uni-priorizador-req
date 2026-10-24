"""Utilidades de texto compartidas por el dominio."""

import unicodedata


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin acentos (ñ → n) y con los espacios colapsados, para comparar frases."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return " ".join(sin_acentos.casefold().split())
