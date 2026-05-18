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

    tag = TigerTag.from_pages(payload, uid=uid)   # from NFC SDK
    tag = TigerTag.from_dump(data)                # from binary dump
    tag = TigerTag.from_file("dump.bin")          # from file

    print(tag.pretty())       # human-readable
    print(tag.to_dict())      # dict for JSON / API
    print(tag.verify())       # ECDSA signature result
"""

from tigertag.tag import TigerTag
from tigertag.db import TigerTagDB, sync_databases
from tigertag.signature import SignatureResult

__version__ = "1.0.0"
__all__ = ["TigerTag", "TigerTagDB", "SignatureResult", "sync_databases"]
