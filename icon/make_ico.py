#!/usr/bin/env python3
"""把 icon/icon-{16,20,24,32,48,64,96,256}.png 合成为多尺寸 iconDesktop.ico。

帧编码：<=96 走 32 位 BMP（所有 Windows 版本兼容），256 走 PNG（Vista+，体积小）。
重新生成流程：在 preview.html 里导出 8 帧 PNG 覆盖后，运行 `python icon/make_ico.py`。
"""
import io
import struct
from pathlib import Path

from PIL import Image

SIZES = [16, 20, 24, 32, 48, 64, 96, 256]
HERE = Path(__file__).resolve().parent


def bmp_frame(img):
    """RGBA Image -> 32 位 BMP 帧（BITMAPINFOHEADER + 自下而上 BGRA 像素 + AND 掩码）。"""
    w, h = img.size
    px = img.load()
    xor = bytearray(w * h * 4)
    and_row = (w + 31) // 32 * 4  # AND 掩码每行 1bpp，按 4 字节对齐
    and_mask = bytearray(and_row * h)
    for y in range(h):
        src_y = h - 1 - y
        base = y * w * 4
        for x in range(w):
            r, g, b, a = px[x, src_y]
            i = base + x * 4
            xor[i] = b
            xor[i + 1] = g
            xor[i + 2] = r
            xor[i + 3] = a
            if a == 0:
                and_mask[y * and_row + x // 8] |= 0x80 >> (x % 8)
    header = struct.pack(
        "<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0
    )
    return header + bytes(xor) + bytes(and_mask)


def build_ico():
    frames = []
    for s in SIZES:
        img = Image.open(HERE / f"icon-{s}.png").convert("RGBA")
        assert img.size == (s, s), f"icon-{s}.png 尺寸异常: {img.size}"
        if s >= 256:
            buf = io.BytesIO()
            img.save(buf, "PNG")
            frames.append(buf.getvalue())
        else:
            frames.append(bmp_frame(img))
        img.close()

    out = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    offset = 6 + 16 * len(frames)
    for s, data in zip(SIZES, frames):
        dim = s if s < 256 else 0  # 目录项里 0 表示 256
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for data in frames:
        out += data
    (HERE / "iconDesktop.ico").write_bytes(out)
    print(f"iconDesktop.ico: {len(out)} bytes, {len(frames)} frames")


def verify():
    data = (HERE / "iconDesktop.ico").read_bytes()
    _, typ, count = struct.unpack("<HHH", data[:6])
    assert typ == 1 and count == len(SIZES), f"目录异常: type={typ}, count={count}"
    seen = []
    for i in range(count):
        off = 6 + i * 16
        w, h, _, _, planes, bpp, size, offset = struct.unpack("<BBBBHHII", data[off:off + 16])
        blob = data[offset:offset + size]
        fmt = "PNG" if blob[:4] == b"\x89PNG" else "BMP"
        seen.append(w or 256)
        print(f"  {w or 256}x{h or 256}  {size:>7} B  {fmt}")
        assert (w or 256) == (h or 256), "非正方形帧"
        if fmt == "BMP":
            xor_size = (w or 256) * (h or 256) * 4
            assert size > xor_size, "BMP 帧数据不完整"
        assert planes == 1 and bpp == 32
    assert seen == SIZES, f"帧尺寸不符: {seen}"
    im = Image.open(HERE / "iconDesktop.ico")
    for s in SIZES:
        im.size = (s, s)
        im.load()
        assert im.size == (s, s)
    print("verify: OK")


if __name__ == "__main__":
    build_ico()
    verify()
