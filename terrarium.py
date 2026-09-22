"""Small dependency-free decoder for 8-bit RGB/RGBA Terrarium PNG tiles."""
import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode_png(data):
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid PNG signature")
    pos, compressed, width, height, channels = 8, bytearray(), None, None, None
    saw_end = False
    while pos + 12 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG chunk")
        payload = data[pos + 8:pos + 8 + length]
        crc = struct.unpack_from(">I", data, pos + 8 + length)[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            raise ValueError("PNG checksum mismatch")
        if kind == b"IHDR":
            if length != 13:
                raise ValueError("Invalid PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if not (0 < width <= 4096 and 0 < height <= 4096 and depth == 8 and color in (2, 6)
                    and compression == filtering == interlace == 0):
                raise ValueError("Unsupported PNG format")
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            saw_end = True
            break
        pos = end
    if width is None or not saw_end:
        raise ValueError("Incomplete PNG")
    stride = width * channels
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as exc:
        raise ValueError("Invalid compressed PNG data") from exc
    if len(raw) != height * (stride + 1):
        raise ValueError("Unexpected PNG data size")
    rows, previous, offset = [], bytearray(stride), 0
    for _ in range(height):
        filter_type = raw[offset]
        scan = bytearray(raw[offset + 1:offset + 1 + stride])
        offset += stride + 1
        for i in range(stride):
            a = scan[i - channels] if i >= channels else 0
            b = previous[i]
            c = previous[i - channels] if i >= channels else 0
            if filter_type == 1:
                predictor = a
            elif filter_type == 2:
                predictor = b
            elif filter_type == 3:
                predictor = (a + b) // 2
            elif filter_type == 4:
                p = a + b - c
                distances = (abs(p - a), abs(p - b), abs(p - c))
                predictor = (a, b, c)[distances.index(min(distances))]
            elif filter_type == 0:
                predictor = 0
            else:
                raise ValueError("Unsupported PNG filter")
            scan[i] = (scan[i] + predictor) & 255
        rows.append(scan)
        previous = scan
    return width, height, channels, rows


def decode_terrarium(data):
    width, height, channels, rows = decode_png(data)
    return [[row[i] * 256 + row[i + 1] + row[i + 2] / 256 - 32768
             for i in range(0, width * channels, channels)] for row in rows]
