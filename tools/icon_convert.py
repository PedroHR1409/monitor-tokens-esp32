"""Converte PNGs de marca em icones LVGL (ARGB8888 40x40) — so stdlib.

Pipeline: src/assets/<marca>.png (qualquer tamanho/formato suportado) ->
redimensionado com media de area (respeitando alfa) para caber em 40x40,
centralizado sobre canvas transparente -> src/icons/<marca>_icon.c no mesmo
formato que a LVGLImage.py oficial produz (bytes B,G,R,A por pixel).

Sem PIL de proposito: as tools do projeto sao stdlib-only (ver AGENTS.md).
Um decodificador PNG reduzido (bit depth 8, color types 2/3/6, sem interlace)
cobra ~80 linhas e cobre os PNGs de logo que o projeto usa.

Uso:
    python tools/icon_convert.py src/assets/zai.png src/icons/zai_icon.c
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

ICON_SIZE = 40
BLOCK = b"IDAT"


def _read_chunks(data: bytes):
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        chunk = data[offset + 8:offset + 8 + length]
        yield kind, chunk
        offset += 12 + length


def decode_png(path: Path) -> tuple[int, int, list[list[int]]]:
    """-> (largura, altura, pixels RGBA achatados). Suporta types 2/3/6, depth 8."""
    data = path.read_bytes()
    width = height = 0
    palette: list[tuple[int, int, int]] = []
    trns: list[int] = []
    raw = b""
    for kind, chunk in _read_chunks(data):
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            if depth != 8 or interlace:
                raise ValueError("{}: requer depth 8 sem interlace".format(path.name))
            if ctype not in (2, 3, 6):
                raise ValueError("{}: color type {} nao suportado".format(path.name, ctype))
        elif kind == b"PLTE":
            palette = [tuple(chunk[i:i + 3]) for i in range(0, len(chunk), 3)]
        elif kind == b"tRNS":
            trns = list(chunk)
        elif kind == b"IDAT":
            raw += chunk
    channels = {2: 3, 6: 4, 3: 1}[ctype]
    stride = width * channels
    expected = (stride + 1) * height
    inflated = zlib.decompress(raw)
    if len(inflated) != expected:
        raise ValueError("{}: IDAT com tamanho inesperado".format(path.name))

    pixels = [0] * (width * height * 4)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        filter_ = inflated[pos]
        row = bytearray(inflated[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        bpp = channels
        if filter_ == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif filter_ == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif filter_ == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + (left + prev[i]) // 2) & 0xFF
        elif filter_ == 4:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[i] = (row[i] + pred) & 0xFF
        for x in range(width):
            index = (y * width + x) * 4
            if ctype == 3:
                r, g, b = palette[row[x]]
                alpha = trns[row[x]] if row[x] < len(trns) else 255
            elif ctype == 6:
                r, g, b, alpha = row[x * 4:x * 4 + 4]
            else:
                r, g, b = row[x * 3:x * 3 + 3]
                alpha = 255
            pixels[index:index + 4] = [r, g, b, alpha]
        prev = row
    return width, height, pixels


def resize_fit(width: int, height: int, pixels: list[int]) -> list[int]:
    """Escala preservando proporcao para caber em ICON_SIZE e centraliza.

    Media de area por acumulacao de ORIGEM para DESTINO: cada pixel de origem cai
    inteiro em um balde do canvas (pre-multiplicado por alfa), o que nunca deixa
    buracos por erro de arredondamento no mapeamento inverso."""
    scale = min(ICON_SIZE / width, ICON_SIZE / height)
    target_w = max(int(round(width * scale)), 1)
    target_h = max(int(round(height * scale)), 1)
    offset_x = (ICON_SIZE - target_w) // 2
    offset_y = (ICON_SIZE - target_h) // 2
    accum = [[0, 0, 0, 0, 0] for _ in range(target_w * target_h)]  # r,g,b,a,count
    for sy in range(height):
        ty0 = int(sy * scale)
        ty1 = max(int((sy + 1) * scale), ty0 + 1)
        for sx in range(width):
            tx0 = int(sx * scale)
            tx1 = max(int((sx + 1) * scale), tx0 + 1)
            index = (sy * width + sx) * 4
            alpha = pixels[index + 3]
            for ty in range(min(ty0, target_h - 1), min(ty1, target_h)):
                for tx in range(min(tx0, target_w - 1), min(tx1, target_w)):
                    bucket = accum[ty * target_w + tx]
                    bucket[0] += pixels[index] * alpha
                    bucket[1] += pixels[index + 1] * alpha
                    bucket[2] += pixels[index + 2] * alpha
                    bucket[3] += alpha
                    bucket[4] += 1
    canvas = [0] * (ICON_SIZE * ICON_SIZE * 4)
    for ty in range(target_h):
        for tx in range(target_w):
            total_r, total_g, total_b, total_a, count = accum[ty * target_w + tx]
            alpha = total_a // count if count else 0
            if not alpha:
                continue
            index = ((ty + offset_y) * ICON_SIZE + (tx + offset_x)) * 4
            canvas[index] = total_r // total_a
            canvas[index + 1] = total_g // total_a
            canvas[index + 2] = total_b // total_a
            canvas[index + 3] = alpha
    return canvas


def render_c(symbol: str, pixels: list[int]) -> str:
    lines = []
    for y in range(ICON_SIZE):
        row = pixels[y * ICON_SIZE * 4:(y + 1) * ICON_SIZE * 4]
        # LVGL ARGB8888: memoria little-endian de 0xAARRGGBB -> B,G,R,A
        groups = ["0x{:02x},0x{:02x},0x{:02x},0x{:02x}".format(
            row[i + 2], row[i + 1], row[i], row[i + 3]) for i in range(0, len(row), 4)]
        lines.append("    " + ",".join(groups) + ",")
    return '''#include <lvgl.h>

#ifndef LV_ATTRIBUTE_MEM_ALIGN
#define LV_ATTRIBUTE_MEM_ALIGN
#endif

#ifndef LV_ATTRIBUTE_{upper}
#define LV_ATTRIBUTE_{upper}
#endif

static const
LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_LARGE_CONST LV_ATTRIBUTE_{upper}
uint8_t {symbol}_map[] = {{
{data}
}};

const lv_image_dsc_t {symbol} = {{
  .header = {{
    .magic = LV_IMAGE_HEADER_MAGIC,
    .cf = LV_COLOR_FORMAT_ARGB8888,
    .flags = 0,
    .w = {size},
    .h = {size},
    .stride = {stride},
    .reserved_2 = 0,
  }},
  .data_size = sizeof({symbol}_map),
  .data = {symbol}_map,
  .reserved = NULL,
}};
'''.format(upper=symbol.upper(), symbol=symbol, data="\n".join(lines),
           size=ICON_SIZE, stride=ICON_SIZE * 4)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    source, destination = Path(argv[1]), Path(argv[2])
    width, height, pixels = decode_png(source)
    symbol = destination.stem
    destination.write_text(render_c(symbol, resize_fit(width, height, pixels)),
                           encoding="utf-8", newline="\n")
    print("{}: {}x{} -> {} ({}x{})".format(source.name, width, height,
                                           destination.name, ICON_SIZE, ICON_SIZE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
