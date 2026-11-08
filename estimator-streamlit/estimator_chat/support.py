"""Utilidades sin dependencia de Streamlit que soportan `streamlit_app.py`."""

# Una transcripción de 80 000 caracteres ocupa como mucho ~320 KB en UTF-8.
MAX_TRANSCRIPT_BYTES = 400_000


def decode_transcript(data: bytes) -> str:
    """Texto de un archivo .txt subido; lanza ValueError con un mensaje apto para el usuario."""
    if len(data) > MAX_TRANSCRIPT_BYTES:
        raise ValueError(f"El archivo supera el máximo de {MAX_TRANSCRIPT_BYTES // 1000} KB.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("El archivo debe estar codificado en UTF-8.") from None
