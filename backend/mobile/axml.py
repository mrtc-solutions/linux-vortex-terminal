"""Minimal Android binary XML (AXML) encoder.

Produces the resource-table XML used inside APKs. Only the constructs needed
for VORTEX's WebView manifest are implemented. Values are typed; nothing is
left as plaintext XML inside the APK.
"""
from __future__ import annotations

import struct
from typing import Iterable

RES_XML_TYPE = 0x0003
RES_STRING_POOL_TYPE = 0x0001
RES_XML_RESOURCE_MAP_TYPE = 0x0180
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103

CHUNK_HEADER = 8
ATTR_VALUE_STRING = 0x03
ATTR_VALUE_INT_DEC = 0x10
ATTR_VALUE_INT_BOOLEAN = 0x12
ATTR_SIZE = 20

ANDROID_NS = "http://schemas.android.com/apk/res/android"

# Documented platform attribute resource IDs (public.xml).
ATTR_IDS = {
    "theme": 0x01010000,
    "label": 0x01010001,
    "icon": 0x01010002,
    "name": 0x01010003,
    "debuggable": 0x0101000F,
    "exported": 0x01010010,
    "permission": 0x01010006,
    "minSdkVersion": 0x0101020C,
    "versionCode": 0x0101021B,
    "versionName": 0x0101021C,
    "targetSdkVersion": 0x01010270,
    "usesCleartextTraffic": 0x010104EC,
    "hardwareAccelerated": 0x010102D3,
    "configChanges": 0x0101001F,
}


def _u16(n: int) -> bytes:
    return struct.pack("<H", n)


def _u32(n: int) -> bytes:
    return struct.pack("<I", n)


def _s32(n: int) -> bytes:
    return struct.pack("<i", n)


def _pad4(data: bytes) -> bytes:
    pad = (4 - (len(data) % 4)) % 4
    return data + (b"\x00" * pad)


def _utf16_string(value: str) -> bytes:
    encoded = value.encode("utf-16le")
    # uint16 char count, then data, then 0x0000 terminator.
    return _u16(len(value)) + encoded + b"\x00\x00"


def _string_pool(strings: list[str]) -> bytes:
    body = b""
    offsets: list[int] = []
    for item in strings:
        offsets.append(len(body))
        body += _utf16_string(item)
        if len(body) % 4:
            body += b"\x00" * (4 - (len(body) % 4))
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    chunk = (
        _u32(len(strings))  # stringCount
        + _u32(0)  # styleCount
        + _u32(0)  # flags (UTF-16)
        + _u32(strings_start)  # stringsStart relative to pool header
        + _u32(0)  # stylesStart
        + b"".join(_u32(off) for off in offsets)
        + body
    )
    total = CHUNK_HEADER + len(chunk)
    return _u16(RES_STRING_POOL_TYPE) + _u16(header_size) + _u32(total) + chunk


def _resource_map(ids: list[int]) -> bytes:
    payload = b"".join(_u32(i) for i in ids)
    total = CHUNK_HEADER + len(payload)
    return _u16(RES_XML_RESOURCE_MAP_TYPE) + _u16(CHUNK_HEADER) + _u32(total) + payload


def _ns_chunk(kind: int, prefix_idx: int, uri_idx: int, line: int = 2) -> bytes:
    header_size = 16
    payload = _u32(prefix_idx) + _u32(uri_idx)
    total = header_size + len(payload)
    return _u16(kind) + _u16(header_size) + _u32(total) + _u32(line) + _u32(0xFFFFFFFF) + payload


def _attr(ns: int, name: int, raw: int, typed: tuple[int, int]) -> bytes:
    type_code, data = typed
    return _s32(ns) + _u32(name) + _s32(raw) + _u16(ATTR_SIZE) + bytes([0, type_code]) + _u32(data)


def _start_element(ns: int, name: int, attrs: list[bytes], line: int = 3) -> bytes:
    header_size = 16
    # id/class/style indices: 0x00100000 means "none" in the attribute index field.
    ext = _s32(ns) + _u32(name) + _u16(0x0014) + _u16(len(attrs)) + _u16(0) + _u16(0) + _u16(0)
    payload = ext + b"".join(attrs)
    total = header_size + len(payload)
    return _u16(RES_XML_START_ELEMENT_TYPE) + _u16(header_size) + _u32(total) + _u32(line) + _u32(0xFFFFFFFF) + payload


def _end_element(ns: int, name: int, line: int = 4) -> bytes:
    header_size = 16
    payload = _s32(ns) + _u32(name)
    total = header_size + len(payload)
    return _u16(RES_XML_END_ELEMENT_TYPE) + _u16(header_size) + _u32(total) + _u32(line) + _u32(0xFFFFFFFF) + payload


class _Pool:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.index: dict[str, int] = {}

    def add(self, value: str) -> int:
        if value not in self.index:
            self.index[value] = len(self.items)
            self.items.append(value)
        return self.index[value]


def encode_manifest(
    *,
    package: str = "io.vortex.mobile",
    version_code: int = 219,
    version_name: str = "0.2.20",
    label: str = "VORTEX",
    activity: str = "io.vortex.mobile.MainActivity",
    min_sdk: int = 21,
    target_sdk: int = 34,
) -> bytes:
    """Encode a launchable WebView application manifest."""
    pool = _Pool()
    # Resource-map attributes must occupy the first N string-pool slots so the
    # resourceIds[i] corresponds to strings[i].
    res_names = [
        "theme", "label", "name", "exported", "minSdkVersion", "versionCode",
        "versionName", "targetSdkVersion", "usesCleartextTraffic", "hardwareAccelerated",
        "configChanges",
    ]
    for name in res_names:
        pool.add(name)
    res_ids = [ATTR_IDS[name] for name in res_names]

    def s(value: str) -> int:
        return pool.add(value)

    android = s("android")
    uri = s(ANDROID_NS)
    manifest = s("manifest")
    package_attr = s("package")
    uses_sdk = s("uses-sdk")
    uses_permission = s("uses-permission")
    application = s("application")
    activity_el = s("activity")
    intent_filter = s("intent-filter")
    action = s("action")
    category = s("category")
    pkg_val = s(package)
    ver_name_val = s(version_name)
    label_val = s(label)
    activity_val = s(activity)
    internet = s("android.permission.INTERNET")
    action_main = s("android.intent.action.MAIN")
    cat_launcher = s("android.intent.category.LAUNCHER")
    # configChanges value as raw string is not used; integer bitmask instead.

    def an(name: str) -> int:
        return pool.index[name]

    def str_attr(name: str, value_idx: int) -> bytes:
        return _attr(android, an(name), value_idx, (ATTR_VALUE_STRING, value_idx))

    def bool_attr(name: str, value: bool) -> bytes:
        return _attr(android, an(name), -1, (ATTR_VALUE_INT_BOOLEAN, 0xFFFFFFFF if value else 0))

    def int_attr(name: str, value: int) -> bytes:
        return _attr(android, an(name), -1, (ATTR_VALUE_INT_DEC, value))

    def raw_str_attr(name_idx: int, value_idx: int) -> bytes:
        return _attr(-1, name_idx, value_idx, (ATTR_VALUE_STRING, value_idx))

    chunks: list[bytes] = []
    line = 2
    chunks.append(_ns_chunk(RES_XML_START_NAMESPACE_TYPE, android, uri, line))
    line += 1
    chunks.append(_start_element(-1, manifest, [
        raw_str_attr(package_attr, pkg_val),
        int_attr("versionCode", version_code),
        str_attr("versionName", ver_name_val),
    ], line))
    line += 1
    chunks.append(_start_element(-1, uses_sdk, [
        int_attr("minSdkVersion", min_sdk),
        int_attr("targetSdkVersion", target_sdk),
    ], line))
    chunks.append(_end_element(-1, uses_sdk, line))
    line += 1
    chunks.append(_start_element(-1, uses_permission, [
        str_attr("name", internet),
    ], line))
    chunks.append(_end_element(-1, uses_permission, line))
    line += 1
    chunks.append(_start_element(-1, application, [
        str_attr("label", label_val),
        bool_attr("usesCleartextTraffic", True),
        bool_attr("hardwareAccelerated", True),
    ], line))
    line += 1
    # configChanges: orientation|keyboardHidden|screenSize = 0x00A0
    chunks.append(_start_element(-1, activity_el, [
        str_attr("name", activity_val),
        str_attr("label", label_val),
        bool_attr("exported", True),
        int_attr("configChanges", 0x00A0),
    ], line))
    line += 1
    chunks.append(_start_element(-1, intent_filter, [], line))
    line += 1
    chunks.append(_start_element(-1, action, [str_attr("name", action_main)], line))
    chunks.append(_end_element(-1, action, line))
    line += 1
    chunks.append(_start_element(-1, category, [str_attr("name", cat_launcher)], line))
    chunks.append(_end_element(-1, category, line))
    chunks.append(_end_element(-1, intent_filter, line))
    chunks.append(_end_element(-1, activity_el, line))
    chunks.append(_end_element(-1, application, line))
    chunks.append(_end_element(-1, manifest, line))
    chunks.append(_ns_chunk(RES_XML_END_NAMESPACE_TYPE, android, uri, line))

    body = _string_pool(pool.items) + _resource_map(res_ids) + b"".join(chunks)
    total = CHUNK_HEADER + len(body)
    return _u16(RES_XML_TYPE) + _u16(CHUNK_HEADER) + _u32(total) + body
