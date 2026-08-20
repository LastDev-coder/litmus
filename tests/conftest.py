from __future__ import annotations

import io
import struct
import zipfile
import zlib

import pytest

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunk(ctype: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + ctype
        + payload
        + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
    )


def build_png(*, text: dict[str, str] | None = None, c2pa: bool = False) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")  # one red pixel scanline
    out = [PNG_SIGNATURE, png_chunk(b"IHDR", ihdr)]
    for key, value in (text or {}).items():
        out.append(png_chunk(b"tEXt", key.encode() + b"\x00" + value.encode()))
    if c2pa:
        out.append(png_chunk(b"caBX", b"\x00\x00\x00\x18jumb" + b"\x00" * 16))
    out.append(png_chunk(b"IDAT", idat))
    out.append(png_chunk(b"IEND", b""))
    return b"".join(out)


def build_jpeg(*, xmp: bool = False, jumbf: bool = False) -> bytes:
    out = [b"\xff\xd8"]

    def segment(marker: int, payload: bytes) -> bytes:
        return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload

    out.append(segment(0xE0, b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00"))
    if xmp:
        out.append(segment(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta/>"))
    if jumbf:
        out.append(segment(0xEB, b"\x00\x00\x00\x18jumb" + b"\x00" * 16))
    out.append(b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00")
    out.append(b"\xff\xd9")
    return b"".join(out)


def _exif_app1_with_gps(make: str = "Canon") -> bytes:
    """A big-endian TIFF EXIF payload with a camera make and GPS coordinates."""
    be = ">"
    ifd0_offset = 8
    ifd0_size = 2 + 2 * 12 + 4  # count + 2 entries + next-offset
    make_bytes = make.encode("ascii") + b"\x00"
    make_offset = ifd0_offset + ifd0_size
    gps_ifd_offset = make_offset + len(make_bytes)
    gps_ifd_size = 2 + 4 * 12 + 4  # count + 4 entries + next-offset
    lat_offset = gps_ifd_offset + gps_ifd_size
    lon_offset = lat_offset + 24  # 3 rationals * 8 bytes

    header = b"MM" + struct.pack(be + "HI", 0x002A, ifd0_offset)
    ifd0 = struct.pack(be + "H", 2)
    ifd0 += struct.pack(be + "HHII", 0x010F, 2, len(make_bytes), make_offset)  # Make
    ifd0 += struct.pack(be + "HHII", 0x8825, 4, 1, gps_ifd_offset)  # GPS IFD pointer
    ifd0 += struct.pack(be + "I", 0)  # no next IFD

    gps = struct.pack(be + "H", 4)
    gps += struct.pack(be + "HHI", 0x0001, 2, 2) + b"N\x00\x00\x00"  # lat ref (inline)
    gps += struct.pack(be + "HHII", 0x0002, 5, 3, lat_offset)  # latitude
    gps += struct.pack(be + "HHI", 0x0003, 2, 2) + b"W\x00\x00\x00"  # lon ref (inline)
    gps += struct.pack(be + "HHII", 0x0004, 5, 3, lon_offset)  # longitude
    gps += struct.pack(be + "I", 0)

    lat = struct.pack(be + "IIIIII", 37, 1, 48, 1, 0, 1)  # 37°48'0" -> 37.8
    lon = struct.pack(be + "IIIIII", 122, 1, 25, 1, 0, 1)  # 122°25'0" -> 122.4166..
    tiff = header + ifd0 + make_bytes + gps + lat + lon
    return b"Exif\x00\x00" + tiff


def build_jpeg_with_gps(make: str = "Canon") -> bytes:
    """A minimal JPEG whose APP1 segment carries EXIF with a GPS location."""
    payload = _exif_app1_with_gps(make)
    seg = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return b"\xff\xd8" + seg + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + b"\xff\xd9"


def build_docx(
    *, author: str = "Jane Doe", company: str = "Acme Corp", custom: bool = True
) -> bytes:
    """Build a minimal but genuine DOCX (ZIP of OOXML parts) with metadata."""
    ns = "http://schemas.openxmlformats.org"
    rels_ct = "application/vnd.openxmlformats-package.relationships+xml"
    doc_ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{ns}/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Default Extension="rels" ContentType="{rels_ct}"/>'
        f'<Override PartName="/word/document.xml" ContentType="{doc_ct}"/>'
        "</Types>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Hello world.</w:t></w:r></w:p></w:body></w:document>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator>{author}</dc:creator>"
        f"<cp:lastModifiedBy>{author}</cp:lastModifiedBy>"
        "<cp:revision>7</cp:revision>"
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        f"<Company>{company}</Company><Application>Microsoft Word</Application>"
        "</Properties>"
    )
    custom_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"'
        ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="ClientCode">'
        "<vt:lpwstr>SECRET-42</vt:lpwstr></property></Properties>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/document.xml", document)
        zf.writestr("docProps/core.xml", core)
        zf.writestr("docProps/app.xml", app)
        if custom:
            zf.writestr("docProps/custom.xml", custom_xml)
    return buf.getvalue()


def build_pdf(
    *,
    author: str = "Jane Doe",
    producer: str = "Acme PDF 1.0",
    xmp: bool = False,
    encrypted: bool = False,
    hex_author: bool = False,
) -> bytes:
    """Build a minimal but genuine PDF: catalog, page, content, Info, valid xref."""
    xmp_body = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
        "<xmp:CreatorTool>SneakyWriter 9000</xmp:CreatorTool>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
        '<?xpacket end="w"?>'
    ).encode("utf-8")

    content = b"BT /F1 12 Tf 72 720 Td (Hello world) Tj ET"
    if hex_author:
        author_value = "<FEFF" + author.encode("utf-16-be").hex().upper() + ">"
    else:
        author_value = f"({author})"

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R" + (b" /Metadata 5 0 R" if xmp else b"") + b" >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
    ]
    if xmp:
        objects.append(
            b"<< /Type /Metadata /Subtype /XML /Length %d >>\nstream\n%s\nendstream"
            % (len(xmp_body), xmp_body)
        )
    info_num = len(objects) + 1
    objects.append(
        f"<< /Author {author_value} /Producer ({producer}) "
        f"/CreationDate (D:20240101120000Z) >>".encode()
    )

    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    trailer = b"<< /Size %d /Root 1 0 R /Info %d 0 R" % (len(objects) + 1, info_num)
    if encrypted:
        trailer += b" /Encrypt 9 0 R"
    trailer += b" >>"
    out += b"trailer\n%s\nstartxref\n%d\n%%%%EOF\n" % (trailer, xref_at)
    return bytes(out)


@pytest.fixture
def clean_text() -> str:
    return "# Title\n\nA plain paragraph of text.\n\n- one\n- two\n"


@pytest.fixture
def dirty_text() -> str:
    """Text carrying every invisible-character class this tool reports."""
    return (
        "\ufeff# Title\r\n"
        "\r\n"
        "A plain\u200b paragraph\u00a0of text.\u200e\n"
        "Trailing spaces here.   \n"
        "\n\n\n\n"
        "Hidden payload:\U000e0048\U000e0049\n"
    )
