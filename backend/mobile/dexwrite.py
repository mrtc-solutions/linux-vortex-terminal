"""Generate a Dalvik executable that launches a WebView.

The class is ``io.vortex.mobile.MainActivity``. ``onCreate`` constructs a
``WebView``, enables JavaScript and DOM storage, attaches a ``WebViewClient``,
and loads the sidecar URL baked in at packaging time. The DEX is rebuilt on
every APK sync so the URL always matches the workbench that produced it.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from typing import Iterable

NO_INDEX = 0xFFFFFFFF
ACC_PUBLIC = 0x1
ACC_PROTECTED = 0x4
ACC_CONSTRUCTOR = 0x10000

TYPE_HEADER_ITEM = 0x0000
TYPE_STRING_ID_ITEM = 0x0001
TYPE_TYPE_ID_ITEM = 0x0002
TYPE_PROTO_ID_ITEM = 0x0003
TYPE_METHOD_ID_ITEM = 0x0005
TYPE_CLASS_DEF_ITEM = 0x0006
TYPE_MAP_LIST = 0x1000
TYPE_TYPE_LIST = 0x1001
TYPE_CLASS_DATA_ITEM = 0x2000
TYPE_CODE_ITEM = 0x2001
TYPE_STRING_DATA_ITEM = 0x2002


def uleb128(value: int) -> bytes:
    if value < 0:
        raise ValueError("uleb128 requires a non-negative integer")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def mutf8(text: str) -> bytes:
    raw = text.encode("utf-8")
    # ASCII and BMP-basic UTF-8 match MUTF-8. Reject NULs; sidecar URLs are ASCII.
    if b"\x00" in raw:
        raise ValueError("MUTF-8 string may not contain NUL")
    return raw + b"\x00"


def _u16(n: int) -> bytes:
    return struct.pack("<H", n)


def _u32(n: int) -> bytes:
    return struct.pack("<I", n)


def _align(buf: bytearray, n: int) -> None:
    while len(buf) % n:
        buf.append(0)


def _invoke(opcode: int, method_idx: int, regs: list[int]) -> bytes:
    count = len(regs)
    padded = regs + [0] * 5
    c, d, e, f, g = padded[:5]
    return bytes([
        opcode,
        (count << 4) | g,
        method_idx & 0xFF,
        (method_idx >> 8) & 0xFF,
        (d << 4) | c,
        (f << 4) | e,
    ])


def _const_string(reg: int, string_idx: int) -> bytes:
    return bytes([0x1A, reg, string_idx & 0xFF, (string_idx >> 8) & 0xFF])


def _new_instance(reg: int, type_idx: int) -> bytes:
    return bytes([0x22, reg, type_idx & 0xFF, (type_idx >> 8) & 0xFF])


def _move_result_object(reg: int) -> bytes:
    return bytes([0x0C, reg])


def _const4(reg: int, value: int) -> bytes:
    return bytes([0x12, ((value & 0x0F) << 4) | (reg & 0x0F)])


def _return_void() -> bytes:
    return bytes([0x0E, 0x00])


class _Pool:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.index: dict[str, int] = {}

    def add(self, value: str) -> int:
        if value not in self.index:
            self.index[value] = len(self.items)
            self.items.append(value)
        return self.index[value]


def build_webview_dex(sidecar_url: str) -> bytes:
    """Return a complete ``classes.dex`` that loads ``sidecar_url`` in a WebView."""
    if not sidecar_url or len(sidecar_url) > 400 or "\x00" in sidecar_url:
        raise ValueError("sidecar URL is invalid")
    strings = _Pool()

    def S(value: str) -> int:
        return strings.add(value)

    # Strings that become type descriptors must exist in the string pool.
    t_activity = S("Landroid/app/Activity;")
    t_bundle = S("Landroid/os/Bundle;")
    t_context = S("Landroid/content/Context;")
    t_view = S("Landroid/view/View;")
    t_webview = S("Landroid/webkit/WebView;")
    t_settings = S("Landroid/webkit/WebSettings;")
    t_client = S("Landroid/webkit/WebViewClient;")
    t_void = S("V")
    t_bool = S("Z")
    t_string = S("Ljava/lang/String;")
    t_main = S("Lio/vortex/mobile/MainActivity;")
    n_init = S("<init>")
    n_oncreate = S("onCreate")
    n_getsettings = S("getSettings")
    n_setjs = S("setJavaScriptEnabled")
    n_setdom = S("setDomStorageEnabled")
    n_setclient = S("setWebViewClient")
    n_loadurl = S("loadUrl")
    n_setcontent = S("setContentView")
    url_idx = S(sidecar_url)
    shorty_v = S("V")
    shorty_vl = S("VL")
    shorty_vz = S("VZ")
    shorty_l = S("L")

    # Type ids follow string order of the descriptors we care about; we build
    # a dedicated type list from descriptor strings.
    type_descriptors = [
        "Landroid/app/Activity;",
        "Landroid/os/Bundle;",
        "Landroid/content/Context;",
        "Landroid/view/View;",
        "Landroid/webkit/WebView;",
        "Landroid/webkit/WebSettings;",
        "Landroid/webkit/WebViewClient;",
        "V",
        "Z",
        "Ljava/lang/String;",
        "Lio/vortex/mobile/MainActivity;",
    ]
    for desc in type_descriptors:
        S(desc)
    type_ids = [strings.index[d] for d in type_descriptors]
    type_of = {d: i for i, d in enumerate(type_descriptors)}

    # proto_ids: shorty, return type_idx, parameters type_list offset (filled later)
    # We create type lists in data later; proto records hold the offset.
    protos_spec = [
        # 0: ()V
        ("V", "V", []),
        # 1: (Bundle)V
        ("VL", "V", ["Landroid/os/Bundle;"]),
        # 2: (Context)V
        ("VL", "V", ["Landroid/content/Context;"]),
        # 3: ()L WebSettings
        ("L", "Landroid/webkit/WebSettings;", []),
        # 4: (Z)V
        ("VZ", "V", ["Z"]),
        # 5: (WebViewClient)V
        ("VL", "V", ["Landroid/webkit/WebViewClient;"]),
        # 6: (String)V
        ("VL", "V", ["Ljava/lang/String;"]),
        # 7: (View)V
        ("VL", "V", ["Landroid/view/View;"]),
    ]

    methods_spec = [
        # 0 Activity.<init>()V
        ("Landroid/app/Activity;", "<init>", 0),
        # 1 Activity.onCreate(Bundle)V
        ("Landroid/app/Activity;", "onCreate", 1),
        # 2 Activity.setContentView(View)V
        ("Landroid/app/Activity;", "setContentView", 7),
        # 3 WebView.<init>(Context)V
        ("Landroid/webkit/WebView;", "<init>", 2),
        # 4 WebView.getSettings()L
        ("Landroid/webkit/WebView;", "getSettings", 3),
        # 5 WebSettings.setJavaScriptEnabled(Z)V
        ("Landroid/webkit/WebSettings;", "setJavaScriptEnabled", 4),
        # 6 WebSettings.setDomStorageEnabled(Z)V
        ("Landroid/webkit/WebSettings;", "setDomStorageEnabled", 4),
        # 7 WebViewClient.<init>()V
        ("Landroid/webkit/WebViewClient;", "<init>", 0),
        # 8 WebView.setWebViewClient(WebViewClient)V
        ("Landroid/webkit/WebView;", "setWebViewClient", 5),
        # 9 WebView.loadUrl(String)V
        ("Landroid/webkit/WebView;", "loadUrl", 6),
        # 10 MainActivity.<init>()V
        ("Lio/vortex/mobile/MainActivity;", "<init>", 0),
        # 11 MainActivity.onCreate(Bundle)V
        ("Lio/vortex/mobile/MainActivity;", "onCreate", 1),
    ]

    # --- code items ---
    # onCreate: 6 registers, ins=2 so p0=v4 this, p1=v5 bundle; locals v0-v3
    # <init>: 1 register, ins=1 so p0=v0 this
    this_r, bundle_r = 4, 5
    v0, v1, v2, v3 = 0, 1, 2, 3

    init_insns = (
        _invoke(0x70, 0, [0])  # invoke-direct {p0}, Activity.<init>
        + _return_void()
    )
    oncreate_insns = (
        _invoke(0x6F, 1, [this_r, bundle_r])  # invoke-super onCreate
        + _new_instance(v0, type_of["Landroid/webkit/WebView;"])
        + _invoke(0x70, 3, [v0, this_r])  # WebView.<init>(this)
        + _invoke(0x6E, 4, [v0])  # getSettings
        + _move_result_object(v1)
        + _const4(v2, 1)
        + _invoke(0x6E, 5, [v1, v2])  # setJavaScriptEnabled
        + _invoke(0x6E, 6, [v1, v2])  # setDomStorageEnabled
        + _new_instance(v3, type_of["Landroid/webkit/WebViewClient;"])
        + _invoke(0x70, 7, [v3])  # WebViewClient.<init>
        + _invoke(0x6E, 8, [v0, v3])  # setWebViewClient
        + _const_string(v3, url_idx)
        + _invoke(0x6E, 9, [v0, v3])  # loadUrl
        + _invoke(0x6E, 2, [this_r, v0])  # setContentView
        + _return_void()
    )

    def code_item(registers: int, ins_size: int, outs_size: int, insns: bytes) -> bytes:
        if len(insns) % 2:
            raise ValueError("instruction stream must be 16-bit aligned")
        units = len(insns) // 2
        header = (
            _u16(registers)
            + _u16(ins_size)
            + _u16(outs_size)
            + _u16(0)  # tries
            + _u32(0)  # debug
            + _u32(units)
            + insns
        )
        if units % 2:
            header += b"\x00\x00"
        return header

    init_code = code_item(1, 1, 1, init_insns)  # this only, outs=1 for super init
    # Wait: init has registers. For constructor:
    # .registers 1  ; p0 = this
    # invoke-direct {p0}, Activity-><init>()V
    # return-void
    # ins_size=1, registers=1, outs_size=1
    oncreate_code = code_item(6, 2, 2, oncreate_insns)

    # --- layout ---
    header_size = 0x70
    n_strings = len(strings.items)
    n_types = len(type_ids)
    n_protos = len(protos_spec)
    n_methods = len(methods_spec)
    n_classes = 1

    string_ids_off = header_size
    type_ids_off = string_ids_off + 4 * n_strings
    proto_ids_off = type_ids_off + 4 * n_types
    field_ids_off = 0
    method_ids_off = proto_ids_off + 12 * n_protos
    class_defs_off = method_ids_off + 8 * n_methods
    data_off = class_defs_off + 32 * n_classes
    # Align data to 4 bytes (already aligned: 0x70 + multiples of 4).

    data = bytearray()
    data_base = data_off

    def here() -> int:
        return data_base + len(data)

    # string_data
    string_data_offs: list[int] = []
    for item in strings.items:
        _align(data, 1)
        string_data_offs.append(here())
        encoded = mutf8(item)
        data.extend(uleb128(len(item)) + encoded)

    # type_lists for protos that have parameters
    type_list_offs: list[int] = []
    for _, _, params in protos_spec:
        if not params:
            type_list_offs.append(0)
            continue
        _align(data, 4)
        type_list_offs.append(here())
        data.extend(_u32(len(params)))
        for p in params:
            data.extend(_u16(type_of[p]))
        if len(params) % 2:
            data.extend(_u16(0))

    # code items
    _align(data, 4)
    init_code_off = here()
    data.extend(init_code)
    _align(data, 4)
    oncreate_code_off = here()
    data.extend(oncreate_code)

    # class_data
    _align(data, 1)
    class_data_off = here()
    class_data = (
        uleb128(0) + uleb128(0) + uleb128(1) + uleb128(1)
        # direct: MainActivity.<init> method idx 10, diff 10 from 0
        + uleb128(10) + uleb128(ACC_PUBLIC | ACC_CONSTRUCTOR) + uleb128(init_code_off)
        # virtual: MainActivity.onCreate method idx 11, diff 1
        + uleb128(1) + uleb128(ACC_PROTECTED) + uleb128(oncreate_code_off)
    )
    data.extend(class_data)

    # map list last
    _align(data, 4)
    map_off = here()
    map_entries = [
        (TYPE_HEADER_ITEM, 1, 0),
        (TYPE_STRING_ID_ITEM, n_strings, string_ids_off),
        (TYPE_TYPE_ID_ITEM, n_types, type_ids_off),
        (TYPE_PROTO_ID_ITEM, n_protos, proto_ids_off),
        (TYPE_METHOD_ID_ITEM, n_methods, method_ids_off),
        (TYPE_CLASS_DEF_ITEM, n_classes, class_defs_off),
        (TYPE_STRING_DATA_ITEM, n_strings, string_data_offs[0]),
        (TYPE_TYPE_LIST, sum(1 for off in type_list_offs if off), next(off for off in type_list_offs if off)),
        (TYPE_CODE_ITEM, 2, init_code_off),
        (TYPE_CLASS_DATA_ITEM, 1, class_data_off),
        (TYPE_MAP_LIST, 1, map_off),
    ]
    map_buf = _u32(len(map_entries))
    for typ, size, off in map_entries:
        map_buf += _u16(typ) + _u16(0) + _u32(size) + _u32(off)
    data.extend(map_buf)

    file_size = data_off + len(data)

    # ids sections
    string_ids = b"".join(_u32(off) for off in string_data_offs)
    type_ids_bytes = b"".join(_u32(sidx) for sidx in type_ids)
    proto_ids_bytes = b""
    for (shorty, ret, _), tloff in zip(protos_spec, type_list_offs):
        proto_ids_bytes += _u32(strings.index[shorty]) + _u32(type_of[ret]) + _u32(tloff)
    method_ids_bytes = b""
    for cls, name, proto in methods_spec:
        method_ids_bytes += _u16(type_of[cls]) + _u16(proto) + _u32(strings.index[name])
    class_def = (
        _u32(type_of["Lio/vortex/mobile/MainActivity;"])
        + _u32(ACC_PUBLIC)
        + _u32(type_of["Landroid/app/Activity;"])
        + _u32(0)
        + _u32(NO_INDEX)
        + _u32(0)
        + _u32(class_data_off)
        + _u32(0)
    )

    ids = string_ids + type_ids_bytes + proto_ids_bytes + method_ids_bytes + class_def
    assert data_off == header_size + len(ids)

    header = bytearray(header_size)
    header[0:8] = b"dex\n035\x00"
    # checksum and signature filled later
    struct.pack_into("<I", header, 32, file_size)
    struct.pack_into("<I", header, 36, header_size)
    struct.pack_into("<I", header, 40, 0x12345678)
    struct.pack_into("<I", header, 44, 0)  # link_size
    struct.pack_into("<I", header, 48, 0)  # link_off
    struct.pack_into("<I", header, 52, map_off)
    struct.pack_into("<I", header, 56, n_strings)
    struct.pack_into("<I", header, 60, string_ids_off)
    struct.pack_into("<I", header, 64, n_types)
    struct.pack_into("<I", header, 68, type_ids_off)
    struct.pack_into("<I", header, 72, n_protos)
    struct.pack_into("<I", header, 76, proto_ids_off)
    struct.pack_into("<I", header, 80, 0)  # field_ids_size
    struct.pack_into("<I", header, 84, 0)  # field_ids_off
    struct.pack_into("<I", header, 88, n_methods)
    struct.pack_into("<I", header, 92, method_ids_off)
    struct.pack_into("<I", header, 96, n_classes)
    struct.pack_into("<I", header, 100, class_defs_off)
    struct.pack_into("<I", header, 104, len(data))
    struct.pack_into("<I", header, 108, data_off)

    body = bytes(header) + ids + bytes(data)
    signature = hashlib.sha1(body[32:]).digest()
    checksum = zlib.adler32(signature + body[32:]) & 0xFFFFFFFF
    header[12:32] = signature
    struct.pack_into("<I", header, 8, checksum)
    return bytes(header) + ids + bytes(data)
