import base64
import hashlib
import hmac
import ipaddress
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

passwords = PasswordHasher()
dummy_hash = passwords.hash(secrets.token_urlsafe(32))


def token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint(key: bytes, namespace: str, value: str) -> str:
    return hmac.digest(
        base64.urlsafe_b64decode(key), f"{namespace}:{value}".encode(), "sha256"
    ).hex()


def canonical_ip(host: str) -> str:
    address = ipaddress.ip_address(host)
    mapped = getattr(address, "ipv4_mapped", None)
    return str(mapped or address)


def valid_password(encoded: str, password: str) -> bool:
    try:
        return passwords.verify(encoded, password)
    except VerificationError:
        return False
