# TigerTag RFID Guide
# Copyright (C) 2025 TigerTag
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License.

"""ECDSA-P256 signature verification for TigerTag chips."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

try:
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.serialization import load_pem_public_key as _load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature as _encode_dss_signature
    from cryptography.exceptions import InvalidSignature as _InvalidSignature
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False


class SignatureResult:
    """
    Result of an ECDSA signature verification.

    Attributes:
        status : One of the class constants (VALID, INVALID, UNSIGNED, …)
        ok     : True only when status == VALID
        detail : Human-readable explanation for failures

    Example:
        result = tag.verify()
        if result.ok:
            print("Authentic TigerTag")
        else:
            print(f"Problem: {result}")
    """

    VALID     = "valid"      # signature present and cryptographically correct
    INVALID   = "invalid"    # signature present but verification failed
    UNSIGNED  = "unsigned"   # no signature (all zeros in pages 0x18-0x27)
    NO_CRYPTO = "no_crypto"  # 'cryptography' package not installed
    NO_KEY    = "no_key"     # public key missing from id_version.json
    NO_UID    = "no_uid"     # UID unavailable (partial dump, not 180 bytes)

    _ICONS: Dict[str, str] = {
        VALID:     "✅ VALID",
        INVALID:   "❌ INVALID",
        UNSIGNED:  "⬜ NOT SIGNED",
        NO_CRYPTO: "⚠️  cryptography not installed — run: pip install cryptography",
        NO_KEY:    "⚠️  public key not found in id_version.json",
        NO_UID:    "⚠️  UID unavailable — provide a full 180-byte chip dump",
    }

    def __init__(self, status: str, detail: str = "") -> None:
        self.status = status
        self.detail = detail
        self.ok = status == self.VALID

    def __str__(self) -> str:
        base = self._ICONS.get(self.status, f"? {self.status}")
        return f"{base}  {self.detail}".rstrip()

    def __repr__(self) -> str:
        return f"SignatureResult(status={self.status!r}, ok={self.ok})"

    def to_dict(self) -> Dict[str, object]:
        """Serialize to dict for JSON output."""
        return {"status": self.status, "ok": self.ok, "detail": self.detail}


def verify_signature(
    uid: bytes,
    id_tigertag: int,
    id_product: int,
    signature_r: bytes,
    signature_s: bytes,
    public_key_pem: str,
) -> SignatureResult:
    """
    Verify an ECDSA-P256 signature against TigerTag data.

    Signed message: SHA-256( uid_bytes + block4 + block5 )
      uid_bytes = 7 raw bytes from chip pages 0-1 (ISO 14443, raw binary)
      block4    = id_tigertag as 4-byte big-endian (page 0x04)
      block5    = id_product  as 4-byte big-endian (page 0x05)

    Args:
        uid            : 7-byte chip UID (raw bytes, not hex string)
        id_tigertag    : TigerTag version/format identifier
        id_product     : Product ID (Maker=0xFFFFFFFF, Init=0x00000000)
        signature_r    : 32-byte ECDSA R component
        signature_s    : 32-byte ECDSA S component
        public_key_pem : PEM-encoded ECDSA-P256 public key

    Returns:
        SignatureResult with .ok and .status set
    """
    if not _CRYPTO_AVAILABLE:
        return SignatureResult(SignatureResult.NO_CRYPTO)

    try:
        block4  = id_tigertag.to_bytes(4, "big")
        block5  = id_product.to_bytes(4, "big")
        message = uid + block4 + block5

        r   = int.from_bytes(signature_r, "big")
        s   = int.from_bytes(signature_s, "big")
        der = _encode_dss_signature(r, s)

        pub = _load_pem_public_key(public_key_pem.encode())
        pub.verify(der, message, _ec.ECDSA(_hashes.SHA256()))

        return SignatureResult(SignatureResult.VALID)

    except _InvalidSignature:
        return SignatureResult(
            SignatureResult.INVALID,
            "Signature does not match — tag may be cloned or tampered.",
        )
    except Exception as exc:
        return SignatureResult(SignatureResult.INVALID, f"Verification error: {exc}")
