"""IRIS Binary Ninja plugin package bootstrap."""

try:
    import binaryninja  # type: ignore[import-not-found]  # noqa: F401
except Exception:
    binaryninja = None

if binaryninja is not None:
    from . import iris_binaryninja  # noqa: F401
