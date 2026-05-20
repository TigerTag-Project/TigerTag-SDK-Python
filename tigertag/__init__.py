# TigerTag RFID Guide
# Copyright (C) 2025 TigerTag
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License.

"""
tigertag — Python SDK for TigerTag RFID material identification.

Spec    : https://github.com/TigerTag-Project/TigerTag-RFID-Guide
Protocol: TigerTag Open Source v2.1

Quick start:
    from tigertag import TigerTag

    tag = TigerTag.from_pages(uid, payload)        # from NFC SDK
    tag = TigerTag.from_dump(data)                # from binary dump
    tag = TigerTag.from_file("dump.bin")          # from file

    print(tag.pretty())        # human-readable
    print(tag.to_raw_dict())   # raw protocol fields (flat, no resolution)
    print(tag.to_dict())       # enriched dict with labels, hex colors, dates
    print(tag.verify())        # ECDSA signature result
"""

from tigertag.tag import (
    TigerTag, ApiDiff,
    ID_TIGERTAG, ID_TIGERTAG_PLUS, ID_TIGERTAG_INIT,
    MAKER_PRODUCT_ID, INIT_PRODUCT_ID,
)
from tigertag.db import TigerTagDB, sync_databases
from tigertag.signature import SignatureResult

__version__ = "1.1.0"
__all__ = [
    "TigerTag", "TigerTagDB", "SignatureResult", "sync_databases", "ApiDiff",
    "ID_TIGERTAG", "ID_TIGERTAG_PLUS", "ID_TIGERTAG_INIT",
    "MAKER_PRODUCT_ID", "INIT_PRODUCT_ID",
]
