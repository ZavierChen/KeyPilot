from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _input_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def protect_text(text: str) -> bytes:
    """Encrypt text with Windows DPAPI for the current signed-in user."""
    data = text.encode("utf-8")
    source, source_buffer = _input_blob(data)
    encrypted = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "KeyPilot cloud API key",
        None,
        None,
        None,
        0,
        ctypes.byref(encrypted),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(encrypted.pbData, encrypted.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(encrypted.pbData)
        del source_buffer


def unprotect_text(data: bytes) -> str:
    """Decrypt text previously protected by :func:`protect_text`."""
    source, source_buffer = _input_blob(data)
    plain = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(plain)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(plain.pbData, plain.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(plain.pbData)
        del source_buffer


def save_secret(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(protect_text(value))


def load_secret(path: Path) -> str:
    try:
        return unprotect_text(path.read_bytes())
    except (OSError, UnicodeDecodeError):
        return ""


def delete_secret(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


__all__ = ["delete_secret", "load_secret", "protect_text", "save_secret", "unprotect_text"]
