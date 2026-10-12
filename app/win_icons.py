"""直接从文件资源提取图标（ctypes，仅 Windows；其它平台返回 None）。

为什么不用 QFileIconProvider：外壳（SHGetFileInfo / 图像列表）在进程内缓存
文件图标。应用更新覆盖了 exe 之后，同一进程里重新查询仍然返回旧图标——实测
连新建 QFileIconProvider、QPixmapCache.clear()、SHChangeNotify(SHCNE_UPDATEITEM
/ SHCNE_ASSOCCHANGED) 都无法刷新，只有重启进程才行（正是「更新后图标不刷新、
点刷新没用，要重启程序」的根因）。

PrivateExtractIconsW 直接读 PE/ICO 里的图标资源，不经过外壳缓存，实测同进程内
覆盖文件后立刻能取到新图标，因此刷新即可生效。它对非图标文件（txt/目录）、
索引不存在、无图标资源的文件会返回 0 个图标，此时返回 None，由调用方回退到
外壳提取（回退路径的陈旧风险只影响这类少见的条目）。

附带好处：lnk 的 IconLocation 里带的图标索引（如 "app.exe,3"）能真正生效，
而外壳路径拿到的永远是文件的第一个图标。
"""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtGui import QImage

ICON_SIZE = 256          # 默认提取边长（与 icon_grid.ICON_RENDER_SIZE 一致）

_ENABLED = sys.platform == "win32"

if _ENABLED:
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32

    class _ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    class _BITMAP(ctypes.Structure):
        _fields_ = [
            ("bmType", wintypes.LONG),
            ("bmWidth", wintypes.LONG),
            ("bmHeight", wintypes.LONG),
            ("bmWidthBytes", wintypes.LONG),
            ("bmPlanes", wintypes.WORD),
            ("bmBitsPixel", wintypes.WORD),
            ("bmBits", ctypes.c_void_p),
        ]

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    # argtypes/restype 只绑定一次：避免每次调用重新推断，也防止 64 位句柄溢出
    _user32.PrivateExtractIconsW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(wintypes.HICON), ctypes.c_void_p, wintypes.UINT, wintypes.UINT,
    ]
    _user32.PrivateExtractIconsW.restype = wintypes.UINT
    _user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_ICONINFO)]
    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    _gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    _gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
    ]


def _bitmap_size(hbitmap):
    bm = _BITMAP()
    if not _gdi32.GetObjectW(hbitmap, ctypes.sizeof(bm), ctypes.byref(bm)):
        return 0, 0
    return int(bm.bmWidth), abs(int(bm.bmHeight))


def _dib_bits(hbitmap, width, height, bit_count):
    """取位图像素为自顶向下的 DIB 字节串；失败返回 None。"""
    header = _BITMAPINFO()
    header.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    header.bmiHeader.biWidth = width
    header.bmiHeader.biHeight = -height          # 负值 = 自顶向下
    header.bmiHeader.biPlanes = 1
    header.bmiHeader.biBitCount = bit_count
    header.bmiHeader.biCompression = 0           # BI_RGB
    stride = ((width * bit_count + 31) // 32) * 4
    buf = ctypes.create_string_buffer(stride * height)
    dc = _user32.GetDC(None)
    lines = _gdi32.GetDIBits(dc, hbitmap, 0, height, buf, ctypes.byref(header), 0)
    _user32.ReleaseDC(None, dc)
    if lines != height:
        return None
    return buf.raw


# 掩码字节 → 8 个像素的 alpha：掩码位为 0 表示不透明（255），为 1 表示透明（0）
_MASK_BYTE_ALPHA = [
    bytes(0 if (value >> (7 - bit)) & 1 else 255 for bit in range(8))
    for value in range(256)
]


def _mask_alpha(mask_bits, width, height):
    """1bpp AND 掩码 → alpha 字节串（逐字节查表，避免逐像素位运算）。"""
    stride = ((width + 31) // 32) * 4
    row_bytes = (width + 7) // 8
    rows = [
        b"".join(_MASK_BYTE_ALPHA[b] for b in mask_bits[y * stride:y * stride + row_bytes])
        for y in range(height)
    ]
    return b"".join(row[:width] for row in rows)


def _hicon_to_image(hicon):
    info = _ICONINFO()
    if not _user32.GetIconInfo(hicon, ctypes.byref(info)):
        return None
    try:
        if not info.hbmColor:
            return None                # 单色图标：交给外壳路径处理
        width, height = _bitmap_size(info.hbmColor)
        if width <= 0 or height <= 0:
            return None
        bits = _dib_bits(info.hbmColor, width, height, 32)
        if bits is None:
            return None
        if not bits[3::4].strip(b"\x00"):
            # 老式图标没有 alpha 通道（GetDIBits 给全 0），改用 AND 掩码当透明通道
            mask = (
                _dib_bits(info.hbmMask, width, height, 1) if info.hbmMask else None
            )
            alpha = (
                _mask_alpha(mask, width, height) if mask is not None
                else b"\xff" * (width * height)
            )
            pixels = bytearray(bits)
            pixels[3::4] = alpha      # 就地替换 alpha 通道（BGRA 步长 4）
            bits = bytes(pixels)
        image = QImage(bits, width, height, QImage.Format_ARGB32).copy()
        return image
    finally:
        for handle in (info.hbmColor, info.hbmMask):
            if handle:
                _gdi32.DeleteObject(handle)


def extract_icon_image(path, index=0, size=ICON_SIZE):
    """返回文件里的图标 QImage（ARGB32）；取不到返回 None。

    path 可以是 .exe / .dll / .ico / .cpl 等带图标资源的文件；
    index 为图标索引（负值表示资源 ID，与 lnk 的 IconLocation 语义一致）。
    """
    if not _ENABLED:
        return None
    icons = (wintypes.HICON * 1)()
    try:
        count = _user32.PrivateExtractIconsW(
            str(path), int(index), int(size), int(size), icons, None, 1, 0
        )
    except (OSError, ValueError):
        return None
    if not count or not icons[0]:
        return None
    hicon = icons[0]
    try:
        return _hicon_to_image(hicon)
    finally:
        _user32.DestroyIcon(hicon)
