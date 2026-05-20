"""
integrate_nfc_sdk.py — NFC SDK integration patterns.

Shows how to adapt output from various NFC SDKs into TigerTag.from_pages().
All platform-specific sections are commented pseudocode; the Python part at
the bottom is runnable as a simulation.

TigerTag stores all material data on the chip — no network required.
Read pages 0x04-0x27 (36 pages × 4 bytes = 144 bytes) and pass them
along with the 7-byte UID to TigerTag.from_pages().

Run:
    python examples/integrate_nfc_sdk.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tigertag import TigerTag


# ═════════════════════════════════════════════════════════════════════════════
# ANDROID — NfcA / MifareUltralight
# ═════════════════════════════════════════════════════════════════════════════
#
# Kotlin / Java:
#
#   val tag: Tag = intent.getParcelableExtra(NfcAdapter.EXTRA_TAG)
#   val uid: ByteArray = tag.id                    // 7 bytes
#   val mifare = MifareUltralight.get(tag)
#   mifare.connect()
#   // Read 36 pages starting at page 4 (144 bytes total)
#   val pages = mifare.readPages(4)      // reads pages 4-7 (16 bytes)
#   // … repeat for pages 8, 12, 16, … up to page 36
#   // or use a helper that reads all pages at once
#   val payload: ByteArray = readAllUserPages(mifare, startPage=4, count=36)
#   mifare.close()
#
#   // In Python bridge / Kotlin interop:
#   tag = TigerTag.from_pages(bytes(uid), bytes(payload))


# ═════════════════════════════════════════════════════════════════════════════
# iOS — CoreNFC (Swift)
# ═════════════════════════════════════════════════════════════════════════════
#
#   func tagReaderSession(_ session: NFCTagReaderSession,
#                         didDetect tags: [NFCTag]) {
#       guard case .miFare(let mifareTag) = tags.first else { return }
#       session.connect(to: tags.first!) { _ in
#           let uid = Data(mifareTag.identifier)   // 7 bytes
#           // Read pages 4-39 (144 bytes)
#           mifareTag.readNDEF { message, error in ... }
#           // Or raw MiFare read:
#           var payload = Data()
#           for page in stride(from: 4, through: 39, by: 4) {
#               mifareTag.sendMiFareCommand(commandPacket: ...) { data, _ in
#                   payload.append(data)
#               }
#           }
#           // Bridge to Python:
#           tag = TigerTag.from_pages(bytes(uid), bytes(payload))
#       }
#   }


# ═════════════════════════════════════════════════════════════════════════════
# Flutter — flutter_nfc_kit
# ═════════════════════════════════════════════════════════════════════════════
#
#   final tag = await FlutterNfcKit.poll(
#       timeout: Duration(seconds: 10),
#       iosMultipleTagMessage: "Multiple tags found!",
#   );
#   final uid = Uint8List.fromList(
#       List.generate(tag.id.length ~/ 2,
#           (i) => int.parse(tag.id.substring(i*2, i*2+2), radix:16))
#   );
#   // Read 144 bytes starting at page 4
#   final payload = await FlutterNfcKit.transceive(
#       Uint8List.fromList([0x30, 4])  // NTAG READ command, page 4
#   );
#   await FlutterNfcKit.finish();
#
#   // Python side (via platform channel or WASM bridge):
#   tag = TigerTag.from_pages(bytes(uid), bytes(payload))


# ═════════════════════════════════════════════════════════════════════════════
# Python — nfcpy (Linux, ACR122U / PN532)
# ═════════════════════════════════════════════════════════════════════════════
#
#   import nfc
#
#   def on_connect(tag):
#       uid     = tag.identifier           # bytes, 7 bytes for NTAG213
#       payload = tag.read(4, 36)          # read 36 pages starting at page 4
#       # Each nfcpy read() returns 4 bytes per page
#       # 36 pages × 4 bytes = 144 bytes
#       tt = TigerTag.from_pages(uid, payload)
#       print(tt.pretty())
#       return True
#
#   with nfc.ContactlessFrontend("usb") as clf:
#       clf.connect(rdwr={"on-connect": on_connect})


# ═════════════════════════════════════════════════════════════════════════════
# Arduino — MFRC522
# ═════════════════════════════════════════════════════════════════════════════
#
#   #include <MFRC522.h>
#   MFRC522 mfrc522(SS_PIN, RST_PIN);
#   mfrc522.PCD_Init();
#
#   if (mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
#     byte uid[7];
#     memcpy(uid, mfrc522.uid.uidByte, 7);
#     byte payload[144];
#     for (byte page = 4; page < 40; page++) {
#       byte buf[18]; byte bufSize = sizeof(buf);
#       mfrc522.MIFARE_Read(page, buf, &bufSize);
#       memcpy(payload + (page-4)*4, buf, 4);
#     }
#     // Send uid + payload over Serial to Python for processing
#   }


# ═════════════════════════════════════════════════════════════════════════════
# Python simulation — runs directly
# ═════════════════════════════════════════════════════════════════════════════

def _make_demo_payload() -> bytes:
    def p16(v): return struct.pack(">H", v & 0xFFFF)
    def p24(v): v &= 0xFFFFFF; return bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])
    def p32(v): return struct.pack(">I", v & 0xFFFFFFFF)

    return (
        p32(0x01000001) + p32(0xFFFFFFFF)
        + p16(38219) + bytes([1, 0, 0x8E, 0x38]) + p16(1)
        + bytes([255, 128, 0, 255])
        + p24(1000) + bytes([1])
        + p16(195) + p16(215)
        + bytes([60, 6, 55, 65])
        + p32(750_000_000)
        + bytes([200, 200, 200]) + b"\x00"
        + bytes([0, 0, 0]) + b"\x00"
        + p16(125) + b"\x00\x00"
        + b"NFC SDK integration".ljust(28, b"\x00")
        + p24(850) + b"\x00"
    )


def main() -> None:
    # Simulate data received from any NFC SDK
    uid     = bytes.fromhex("04DEADBEEF1234")   # 7-byte UID from NFC SDK
    payload = _make_demo_payload()              # 80 bytes (no signature in this demo)

    print("Simulating data from an NFC SDK read...")
    print(f"  UID:          {uid.hex().upper()}")
    print(f"  Payload size: {len(payload)} bytes")
    print()

    tag = TigerTag.from_pages(uid, payload)
    print(tag.pretty())


if __name__ == "__main__":
    main()
