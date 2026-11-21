def convert_document(data: bytes, ext: str, debug: bool) -> dict:
    """Zaślepka - tu wejdzie pipeline konwersji dokumentu na JSON formularza."""
    return {"ext": ext, "size": len(data)}
