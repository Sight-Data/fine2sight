#!/usr/bin/env python3
# 帆软转换器图标 = sight-data 产品 logo 的变体（紫色渐变 + 上升柱 + 火花），
# 右下角加"转换"角标（双向箭头 ⇄）。产品 logo 源自 sight-data-web/src/assets/images/logo.svg。
# 输出 logo-1024.png + icon.ico；icon.icns 由 iconutil 另行生成。
import math
from PIL import Image, ImageDraw

SZ = 1024
S = SZ / 40.0
PURP1 = (123, 97, 255)
PURP2 = (91, 63, 223)
SPARK = (196, 181, 253)
WHITE = (255, 255, 255)
GLYPH = (107, 77, 245)


def draw_product_base(img):
    grad = Image.new("RGB", (SZ, SZ))
    gp = grad.load()
    for y in range(SZ):
        for x in range(SZ):
            t = (x + y) / (2 * (SZ - 1))
            gp[x, y] = tuple(int(PURP1[i] + (PURP2[i] - PURP1[i]) * t) for i in range(3))
    mask = Image.new("L", (SZ, SZ), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SZ - 1, SZ - 1], radius=int(10 * S), fill=255)
    img.paste(grad, (0, 0), mask)
    for bx, by, bh, op in [(8, 26, 9, 0.70), (15, 20, 15, 0.85), (22, 14, 21, 1.0)]:
        bar = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0))
        ImageDraw.Draw(bar).rounded_rectangle(
            [bx * S, by * S, (bx + 5) * S, (by + bh) * S], radius=1.5 * S,
            fill=(255, 255, 255, int(255 * op)))
        img.alpha_composite(bar)
    d = ImageDraw.Draw(img)
    cx, cy, r = 32 * S, 9 * S, 3 * S
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=SPARK)
    lw = int(1.5 * S)
    for (x1, y1, x2, y2) in [(32, 5, 32, 2.5), (32, 13, 32, 15.5), (28, 9, 25.5, 9), (36, 9, 38.5, 9)]:
        d.line([x1 * S, y1 * S, x2 * S, y2 * S], fill=SPARK, width=lw)


def add_converter_badge(img):
    d = ImageDraw.Draw(img)
    bcx, bcy, br = 800, 800, 178
    d.ellipse([bcx - br, bcy - br, bcx + br, bcy + br], fill=WHITE)
    # 转换：上行箭头向右 + 下行箭头向左（⇄）
    bar = 22
    # 上箭头（向右）
    yt = bcy - 40
    d.rounded_rectangle([bcx - 92, yt - bar // 2, bcx + 60, yt + bar // 2], radius=8, fill=GLYPH)
    d.polygon([(bcx + 50, yt - 40), (bcx + 50, yt + 40), (bcx + 104, yt)], fill=GLYPH)
    # 下箭头（向左）
    yb = bcy + 40
    d.rounded_rectangle([bcx - 60, yb - bar // 2, bcx + 92, yb + bar // 2], radius=8, fill=GLYPH)
    d.polygon([(bcx - 50, yb - 40), (bcx - 50, yb + 40), (bcx - 104, yb)], fill=GLYPH)


img = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0))
draw_product_base(img)
add_converter_badge(img)
img.save("logo-1024.png")
img.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote logo-1024.png + icon.ico", img.size)
