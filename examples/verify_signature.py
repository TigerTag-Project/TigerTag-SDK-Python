"""
verify_signature.py — ECDSA signature verification example.

Demonstrates the full sign → verify flow with an ephemeral key pair.
In production, the public key lives in id_version.json (bundled in the package).

Run:
    pip install tigertag[verify]
    python examples/verify_signature.py
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
except ImportError:
    print("This example requires: pip install tigertag[verify]")
    sys.exit(1)

from tigertag import TigerTag, TigerTagDB, SignatureResult


def _make_unsigned_payload(id_tigertag: int, id_product: int) -> bytes:
    def p16(v): return struct.pack(">H", v & 0xFFFF)
    def p24(v): v &= 0xFFFFFF; return bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])
    def p32(v): return struct.pack(">I", v & 0xFFFFFFFF)

    return (
        p32(id_tigertag)
        + p32(id_product)
        + p16(38219) + bytes([1, 0, 0x8E, 0x38]) + p16(1)
        + bytes([255, 50, 50, 255])
        + p24(1000) + bytes([1])
        + p16(190) + p16(220)
        + bytes([65, 8, 60, 70])
        + p32(756_864_000)
        + bytes([50, 255, 50]) + b"\x00"
        + bytes([50, 50, 255]) + b"\x00"
        + p16(0) + b"\x00\x00"
        + b"Signed spool".ljust(28, b"\x00")
        + p24(1000) + b"\x00"
    )


def main() -> None:
    uid         = bytes.fromhex("04A1B2C3D4E5F6")
    id_tigertag = 0x01000001
    id_product  = 0xFFFFFFFF

    # ── Generate an ephemeral key pair ─────────────────────────────────────────
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key  = private_key.public_key()
    pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    print("Generated ephemeral ECDSA-P256 key pair.")
    print()

    # ── Build the signed payload ───────────────────────────────────────────────
    payload = _make_unsigned_payload(id_tigertag, id_product)

    block4  = id_tigertag.to_bytes(4, "big")
    block5  = id_product.to_bytes(4, "big")
    message = uid + block4 + block5

    der = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    sig_r = r.to_bytes(32, "big")
    sig_s = s.to_bytes(32, "big")

    signed_payload = payload + sig_r + sig_s

    # ── Parse and verify ───────────────────────────────────────────────────────
    tag = TigerTag.from_pages(signed_payload, uid=uid)

    # Inject the test public key into the DB
    db = TigerTagDB(auto_sync=False)
    db._versions = [{"id": id_tigertag, "label": "v2.1", "public_key": pem}]

    result = tag.verify(db)

    print(f"Tag is signed:       {tag.is_signed}")
    print(f"Verification result: {result}")
    print(f"result.ok:           {result.ok}")
    print()

    # ── Tamper the signature — should fail ─────────────────────────────────────
    tampered_r    = bytes([b ^ 0xFF for b in sig_r])
    tampered_payload = payload + tampered_r + sig_s
    tampered_tag  = TigerTag.from_pages(tampered_payload, uid=uid)
    tampered_result = tampered_tag.verify(db)

    print(f"Tampered result:     {tampered_result}")
    print(f"tampered_result.ok:  {tampered_result.ok}")


if __name__ == "__main__":
    main()
