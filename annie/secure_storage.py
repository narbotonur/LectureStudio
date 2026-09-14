"""User-bound DPAPI (Windows) or explicit macOS Keychain; no plaintext fallback."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys

MAGIC = b'ANNIE-DPAPI-1\n'
KEYCHAIN_MAGIC = b'ANNIE-KEYCHAIN-1\n'
KEYCHAIN_SERVICE = 'Annie Lecture Studio'


def _keychain():
    # Never use keyring's auto-selection: third-party plaintext backends are
    # unsuitable for OAuth refresh tokens and API keys.
    from keyring.backends.macOS import Keyring
    return Keyring()


def _keychain_account(path):
    return hashlib.sha256(str(Path(path).resolve()).encode('utf-8')).hexdigest()


def _keychain_reference(path):
    return KEYCHAIN_MAGIC + _keychain_account(path).encode('ascii') + b'\n'


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.annie-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_secret(path, value):
    if sys.platform == 'darwin':
        backend = _keychain()
        account = _keychain_account(path)
        if Path(path).exists() and Path(path).read_bytes() != _keychain_reference(path):
            raise ValueError('Not a Keychain reference for this profile. Sign in again on this Mac.')
        previous = backend.get_password(KEYCHAIN_SERVICE, account)
        backend.set_password(KEYCHAIN_SERVICE, account, json.dumps(value, ensure_ascii=False))
        try:
            atomic_write(path, _keychain_reference(path))
        except Exception:
            # Do not leave an inaccessible item when the reference cannot save.
            if previous is None:
                backend.delete_password(KEYCHAIN_SERVICE, account)
            else:
                backend.set_password(KEYCHAIN_SERVICE, account, previous)
            raise
        return
    if sys.platform != 'win32':
        raise RuntimeError('Secure account storage is currently supported on Windows and macOS only.')
    import win32crypt
    raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
    encrypted = win32crypt.CryptProtectData(raw, 'Annie Lecture Studio', None, None, None, 1)
    atomic_write(path, MAGIC + encrypted)


def read_secret(path):
    raw = Path(path).read_bytes()
    if sys.platform == 'darwin':
        if raw != _keychain_reference(path):
            raise ValueError('Not a Keychain reference for this profile. Sign in again on this Mac.')
        value = _keychain().get_password(KEYCHAIN_SERVICE, _keychain_account(path))
        if value is None:
            raise ValueError('Saved account was not found in this Mac\'s Keychain. Reconnect your account.')
        return json.loads(value)
    if sys.platform != 'win32':
        raise RuntimeError('Secure account storage is currently supported on Windows and macOS only.')
    import win32crypt
    if not raw.startswith(MAGIC):
        raise ValueError('Not an Annie protected credential file.')
    return json.loads(win32crypt.CryptUnprotectData(raw[len(MAGIC):], None, None, None, 1)[1])


def delete_secret(path):
    path = Path(path)
    if not path.exists():
        return
    if sys.platform == 'darwin':
        if path.read_bytes() != _keychain_reference(path):
            raise ValueError('Refusing to delete an unrecognized Keychain reference.')
        backend = _keychain()
        account = _keychain_account(path)
        if backend.get_password(KEYCHAIN_SERVICE, account) is not None:
            backend.delete_password(KEYCHAIN_SERVICE, account)
    elif sys.platform != 'win32':
        raise RuntimeError('Unsupported secure storage platform.')
    path.unlink()
