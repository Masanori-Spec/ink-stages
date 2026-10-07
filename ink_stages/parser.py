"""Fail-closed gzip XOPP v4 profile, based on Xournal++ 1.3.8's loader.

This validates a small local-resource profile, not arbitrary hostile PDF content.
ZIP containers, audio, LaTeX, attachments, custom backgrounds and unknown fields
are deliberately unsupported. Validation never repairs or rewrites documents.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import math
import re
import struct
from xml.parsers import expat
import zlib

from .safety import InkStagesError, Snapshot, fail, read_regular


SOURCE_LIMIT = 8 * 1024 * 1024
XML_LIMIT = 32 * 1024 * 1024
RESOURCE_LIMIT = 16 * 1024 * 1024
RESOURCE_TOTAL_LIMIT = 32 * 1024 * 1024
MAX_PAGES = 64
MAX_LAYERS = 64
MAX_DEPTH = 8
MAX_EVENTS = 200_000
MAX_ATTRIBUTE_BYTES = 1024 * 1024
MAX_LEAF_BYTES = 24 * 1024 * 1024
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z", re.ASCII)
RESOURCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,159}\Z", re.ASCII)
COLORS = {"black", "blue", "red", "green", "gray", "lightblue", "lightgreen", "magenta", "orange", "yellow", "white"}


def bounded_text(value: str, label: str, limit: int = 128, empty: bool = False):
    if len(value) > limit or (not empty and not value.strip()) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        fail(f"Invalid {label}")


def number(value: str, label: str, *, positive=False, maximum=1_000_000) -> float:
    if len(value) > 40 or not NUMBER.fullmatch(value):
        fail(f"Invalid numeric {label}")
    result = float(value)
    if not math.isfinite(result) or abs(result) > maximum or (positive and result <= 0):
        fail(f"Out-of-range {label}")
    return result


def color(value: str):
    if value not in COLORS and not re.fullmatch(r"#[0-9a-fA-F]{8}", value):
        fail("Unsupported color; use a native named color or #RRGGBBAA")


def fields(attrs: dict, required: set, optional: set = frozenset()):
    if not required <= attrs.keys() or not attrs.keys() <= required | optional:
        fail(f"Missing or unsupported attributes: expected {sorted(required)}; got {sorted(attrs)}")


def decode_gzip(data: bytes) -> bytes:
    if not data.startswith(b"\x1f\x8b"):
        fail("Only gzip XOPP is supported; ZIP and plain XML containers are unsupported")
    # Xournal++ probes libzip before gzopen. Refuse ZIP directory signatures even
    # inside gzip bytes so a polyglot cannot give the native loader a different tree.
    if b"PK\x05\x06" in data or b"PK\x06\x06" in data:
        fail("ZIP directory signatures inside gzip are unsupported (ambiguous container)")
    stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        xml = stream.decompress(data, XML_LIMIT + 1)
    except zlib.error as exc:
        raise InkStagesError("Invalid gzip XOPP") from exc
    if len(xml) > XML_LIMIT or stream.unconsumed_tail:
        fail("Decompressed XML exceeds the 32 MiB limit")
    if not stream.eof or stream.unused_data:
        fail("Truncated, concatenated, or trailing-data gzip XOPP is unsupported")
    try:
        xml.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise InkStagesError("XOPP XML must be UTF-8") from exc
    if b"\x00" in xml:
        fail("XOPP XML must be UTF-8 without NUL bytes")
    return xml


def validate_png(data: bytes):
    """Validate bounded noninterlaced PNG framing, CRCs and inflated scanlines."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > RESOURCE_LIMIT:
        fail("Image must be a bounded PNG")
    offset, count, phase = 8, 0, 0
    idat = []
    width = height = rowbytes = color_type = bit_depth = None
    palette = False
    seen = set()
    while offset < len(data):
        count += 1
        if count > 8192 or offset + 12 > len(data):
            fail("Invalid or excessive PNG chunks")
        length, kind = struct.unpack(">I4s", data[offset:offset + 8])
        end = offset + 12 + length
        if end > len(data):
            fail("Truncated PNG chunk")
        body = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[offset + 8 + length:end])[0]
        if binascii.crc32(kind + body) & 0xFFFFFFFF != crc:
            fail("PNG checksum mismatch")
        if count == 1 and kind != b"IHDR":
            fail("PNG must start with IHDR")
        if kind != b"IDAT" and kind in seen:
            fail("Duplicate PNG metadata chunk")
        seen.add(kind)
        if kind == b"IHDR":
            if count != 1 or length != 13:
                fail("Invalid PNG IHDR")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            allowed = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16_777_216):
                fail("PNG dimensions exceed limits")
            if bit_depth not in allowed.get(color_type, set()) or compression or filtering or interlace:
                fail("Unsupported PNG encoding (interlaced PNG is unsupported)")
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
            rowbytes = (width * bit_depth * channels + 7) // 8 + 1
            if rowbytes * height > 64 * 1024 * 1024:
                fail("PNG decoded size exceeds limit")
        elif kind == b"IDAT":
            if phase == 2 or (color_type == 3 and not palette):
                fail("Invalid PNG IDAT ordering")
            phase = 1
            idat.append(body)
        elif kind == b"IEND":
            if length or not idat or end != len(data):
                fail("Invalid PNG end")
            phase = 2
        elif kind == b"PLTE":
            if phase or color_type in {0, 4} or not 0 < length <= 768 or length % 3:
                fail("Invalid PNG palette")
            palette = True
        elif kind in {b"gAMA", b"sRGB", b"pHYs", b"cHRM", b"bKGD", b"tRNS"}:
            if phase:
                fail("PNG metadata after image data is unsupported")
            fixed = {b"gAMA": 4, b"sRGB": 1, b"pHYs": 9, b"cHRM": 32}
            if kind in fixed and length != fixed[kind]:
                fail("Invalid PNG metadata size")
            if kind == b"bKGD" and length != {0: 2, 2: 6, 3: 1, 4: 2, 6: 6}[color_type]:
                fail("Invalid PNG background metadata")
            if kind == b"tRNS" and not ((color_type == 0 and length == 2) or
                    (color_type == 2 and length == 6) or (color_type == 3 and palette and 0 < length <= 256)):
                fail("Invalid PNG transparency metadata")
        else:
            fail(f"Unsupported PNG chunk: {kind!r}")
        offset = end
    if b"IEND" not in seen:
        fail("PNG has no IEND")
    decoder = zlib.decompressobj()
    expected = rowbytes * height
    try:
        raw = decoder.decompress(b"".join(idat), expected + 1)
    except zlib.error as exc:
        raise InkStagesError("Invalid PNG compressed image data") from exc
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        fail("PNG inflated scanline size mismatch")
    if any(raw[pos] > 4 for pos in range(0, expected, rowbytes)):
        fail("Invalid PNG scanline filter")


@dataclass
class Page:
    width: float
    height: float
    layers: list[str] = field(default_factory=list)
    background: dict | None = None


@dataclass
class Document:
    source: Snapshot
    pages: list[Page]
    resources: list[Snapshot]
    pdf_pages: dict[str, int]


class XoppParser:
    def __init__(self, source: Snapshot):
        self.source = source
        self.pages = []
        self.stack = []
        self.events = 0
        self.leaf = []
        self.leaf_size = 0
        self.leaf_attrs = {}
        self.resources = {}
        self.resource_bytes = 0
        self.pdf_resource = None
        self.pdf_pages = {}
        self.inline_bytes = 0

    def event(self):
        self.events += 1
        if self.events > MAX_EVENTS:
            fail("XML event limit exceeded")

    def resource(self, attrs: dict, extension: str) -> str:
        name = attrs["filename"]
        if not RESOURCE_NAME.fullmatch(name) or not name.lower().endswith(extension) or ".." in name:
            fail("Resource filename must be a simple same-directory PDF/PNG basename")
        if attrs["domain"] not in {"absolute", "attach"}:
            fail("Only relative-path or gzip attached resources are supported; clones are unsupported")
        actual_name = self.source.path.name + "." + name if attrs["domain"] == "attach" else name
        path = self.source.path.parent / actual_name
        if path == self.source.path:
            fail("Resource aliases the source")
        if actual_name not in self.resources:
            if len(self.resources) >= 64:
                fail("Resource count limit exceeded")
            resource = read_regular(path, RESOURCE_LIMIT)
            if (resource.device, resource.inode) == (self.source.device, self.source.inode):
                fail("Resource aliases the source inode")
            self.resource_bytes += len(resource.data)
            if self.resource_bytes > RESOURCE_TOTAL_LIMIT:
                fail("Resource total exceeds 32 MiB")
            if extension == ".png":
                validate_png(resource.data)
            elif not re.match(rb"%PDF-[12]\.[0-9](?:\r|\n)", resource.data):
                fail("PDF resource must start with a PDF version header")
            self.resources[actual_name] = resource
        return actual_name

    def start(self, tag: str, attrs: dict):
        self.event()
        if len(self.stack) >= MAX_DEPTH:
            fail("XML depth limit exceeded")
        if sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in attrs.items()) > MAX_ATTRIBUTE_BYTES:
            fail("XML attribute limit exceeded")
        parent = self.stack[-1] if self.stack else None
        allowed = {None: {"xournal"}, "xournal": {"title", "preview", "page"},
                   "page": {"background", "layer"}, "layer": {"stroke", "text", "image"}}
        if tag not in allowed.get(parent, set()):
            fail(f"Unsupported XML element or nesting: {tag}")
        if tag == "xournal":
            fields(attrs, {"fileversion"}, {"creator", "version"})
            if attrs["fileversion"] != "4":
                fail("Only XOPP fileversion=4 is supported")
            for value in attrs.values():
                bounded_text(value, "document metadata", 512)
        elif tag == "page":
            fields(attrs, {"width", "height"})
            if len(self.pages) >= MAX_PAGES:
                fail("Page count exceeds 64")
            self.pages.append(Page(number(attrs["width"], "page width", positive=True, maximum=20_000),
                                   number(attrs["height"], "page height", positive=True, maximum=20_000)))
        elif tag == "background":
            page = self.pages[-1]
            if page.background is not None or page.layers:
                fail("Each page needs one background before its layers")
            kind = attrs.get("type")
            if kind == "solid":
                fields(attrs, {"type", "color", "style"}, {"name"})
                color(attrs["color"])
                if attrs["style"] not in {"plain", "ruled", "lined", "graph", "staves", "dotted", "isodotted", "isograph"}:
                    fail("Unsupported solid background style")
            elif kind == "pixmap":
                fields(attrs, {"type", "domain", "filename"}, {"name"})
                self.resource(attrs, ".png")
            elif kind == "pdf":
                fields(attrs, {"type", "pageno"}, {"domain", "filename", "name"})
                if not re.fullmatch(r"[1-9][0-9]{0,4}", attrs["pageno"]):
                    fail("Invalid PDF background page number")
                if self.pdf_resource is None:
                    if not {"domain", "filename"} <= attrs.keys():
                        fail("First PDF background needs domain and filename")
                    self.pdf_resource = self.resource(attrs, ".pdf")
                elif "domain" in attrs or "filename" in attrs:
                    fail("Later PDF backgrounds must inherit the first PDF resource, as native saves do")
                self.pdf_pages[self.pdf_resource] = max(int(attrs["pageno"]), self.pdf_pages.get(self.pdf_resource, 0))
            else:
                fail("Unsupported background type")
            if "name" in attrs:
                bounded_text(attrs["name"], "background name")
            page.background = dict(attrs)
        elif tag == "layer":
            fields(attrs, {"name"})
            page = self.pages[-1]
            if page.background is None:
                fail("Page background must precede layers")
            bounded_text(attrs["name"], "layer name")
            if attrs["name"] in page.layers:
                fail(f"Duplicate layer name on page {len(self.pages)}: {attrs['name']!r}")
            if len(page.layers) >= MAX_LAYERS:
                fail("Layer count exceeds 64 on a page")
            page.layers.append(attrs["name"])
        elif tag == "stroke":
            fields(attrs, {"tool", "color", "width"}, {"fill", "capStyle"})
            if attrs["tool"] not in {"pen", "highlighter", "eraser"}:
                fail("Unsupported stroke tool")
            color(attrs["color"])
            widths = attrs["width"].split(maxsplit=50_001)
            if not 1 <= len(widths) <= 50_001:
                fail("Stroke width count exceeds limit")
            for width in widths:
                number(width, "stroke width", positive=True, maximum=10_000)
            if "capStyle" in attrs and attrs["capStyle"] not in {"butt", "round", "square"}:
                fail("Unsupported stroke cap")
            if "fill" in attrs and (not re.fullmatch(r"[0-9]{1,3}", attrs["fill"]) or int(attrs["fill"]) > 255):
                fail("Invalid stroke fill")
        elif tag == "text":
            fields(attrs, {"font", "size", "x", "y", "color"})
            bounded_text(attrs["font"], "font", 256)
            number(attrs["size"], "font size", positive=True, maximum=10_000)
            number(attrs["x"], "text x")
            number(attrs["y"], "text y")
            color(attrs["color"])
        elif tag == "image":
            fields(attrs, {"left", "top", "right", "bottom"})
            values = {key: number(value, f"image {key}") for key, value in attrs.items()}
            if values["right"] <= values["left"] or values["bottom"] <= values["top"]:
                fail("Image dimensions must be positive")
        else:
            fields(attrs, set())
        self.stack.append(tag)
        if tag in {"stroke", "text", "image", "title", "preview"}:
            self.leaf, self.leaf_size, self.leaf_attrs = [], 0, dict(attrs)

    def data(self, text: str):
        self.event()
        if self.stack and self.stack[-1] in {"stroke", "text", "image", "title", "preview"}:
            self.leaf_size += len(text.encode("utf-8"))
            limit = min(MAX_LEAF_BYTES, {"stroke": 4 * 1024 * 1024, "text": 1024 * 1024,
                                        "title": 64 * 1024}.get(self.stack[-1], MAX_LEAF_BYTES))
            if self.leaf_size > limit:
                fail("XML leaf text exceeds limit")
            self.leaf.append(text)
        elif text.strip():
            fail("Unexpected text outside a supported leaf element")

    def end(self, tag: str):
        self.event()
        if tag == "page" and (not self.pages[-1].layers or self.pages[-1].background is None):
            fail("Every page must have a background and at least one named layer")
        if tag == "xournal" and not self.pages:
            fail("Document has no pages")
        if tag == "stroke":
            tokens = "".join(self.leaf).split(maxsplit=100_000)
            if not 4 <= len(tokens) <= 100_000 or len(tokens) % 2:
                fail("A stroke needs 2..50000 complete coordinate pairs")
            for token in tokens:
                number(token, "stroke coordinate")
            count = len(self.leaf_attrs["width"].split())
            if count != 1 and count not in {len(tokens) // 2, len(tokens) // 2 + 1}:
                fail("Pressure width count does not match stroke points")
        elif tag in {"image", "preview"}:
            content = "".join(self.leaf)
            try:
                encoded = re.sub(r"[\t\r\n ]", "", content).encode("ascii")
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, UnicodeError) as exc:
                raise InkStagesError("Invalid base64 PNG") from exc
            self.inline_bytes += len(data)
            if self.inline_bytes + self.resource_bytes > RESOURCE_TOTAL_LIMIT:
                fail("Inline images and resources exceed 32 MiB")
            validate_png(data)
        elif tag in {"title", "text"} and self.leaf_size > 1024 * 1024:
            fail("Text exceeds 1 MiB limit")
        self.stack.pop()
        if tag in {"stroke", "text", "image", "title", "preview"}:
            self.leaf = []

    def parse(self) -> Document:
        xml = decode_gzip(self.source.data)
        parser = expat.ParserCreate(encoding="UTF-8")
        parser.StartElementHandler = self.start
        parser.EndElementHandler = self.end
        parser.CharacterDataHandler = self.data
        parser.StartDoctypeDeclHandler = lambda *_: fail("XML DTD is unsupported")
        parser.EntityDeclHandler = lambda *_: fail("XML entities are unsupported")
        parser.ExternalEntityRefHandler = lambda *_: fail("External XML entities are unsupported")
        parser.ProcessingInstructionHandler = lambda *_: fail("XML processing instructions are unsupported")
        # GMarkup's native text callback treats leaf fragments separately.
        # Native saves emit neither comments nor CDATA, so fail closed rather
        # than validate a concatenated value the native loader may not see.
        parser.CommentHandler = lambda *_: fail("XML comments are unsupported")
        parser.StartCdataSectionHandler = lambda *_: fail("XML CDATA is unsupported")
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

        def declaration(version, encoding, _standalone):
            if version != "1.0" or (encoding and encoding.lower().replace("-", "") != "utf8"):
                fail("Only XML 1.0 UTF-8 declarations are supported")

        parser.XmlDeclHandler = declaration
        try:
            for start in range(0, len(xml), 65536):
                parser.Parse(xml[start:start + 65536], False)
            parser.Parse(b"", True)
        except expat.ExpatError as exc:
            raise InkStagesError(f"Invalid XML at line {exc.lineno}: {exc}") from exc
        if self.inline_bytes + self.resource_bytes > RESOURCE_TOTAL_LIMIT:
            fail("Inline images and resources exceed 32 MiB")
        return Document(self.source, self.pages, list(self.resources.values()), self.pdf_pages)


def inspect_xopp(path) -> Document:
    return XoppParser(read_regular(path, SOURCE_LIMIT)).parse()
