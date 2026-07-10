# SPDX-License-Identifier: Apache-2.0
#
# TigerTag SDK
# Copyright (c) 2025-2026 TigerTag Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Implementing the TigerTag protocol requires no licence and no payment.
# https://github.com/TigerTag-Project/TigerTag-RFID-Guide/blob/main/LICENSING.md

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

__version__ = "1.2.1"
__all__ = [
    "TigerTag", "TigerTagDB", "SignatureResult", "sync_databases", "ApiDiff",
    "ID_TIGERTAG", "ID_TIGERTAG_PLUS", "ID_TIGERTAG_INIT",
    "MAKER_PRODUCT_ID", "INIT_PRODUCT_ID",
]
