"""Draw the SkyMate app icon (sun behind a cloud) as a multi-size .ico file."""
import sys

from PIL import Image, ImageDraw, ImageFilter


def draw(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(56 * s), fill=(11, 95, 165, 255))
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([int(60 * s), int(40 * s), int(180 * s), int(160 * s)], fill=(255, 214, 90, 160))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14 * s)))
    d.ellipse([int(72 * s), int(52 * s), int(168 * s), int(148 * s)], fill=(255, 200, 40, 255))
    cloud = (255, 255, 255, 255)
    d.ellipse([int(96 * s), int(118 * s), int(176 * s), int(198 * s)], fill=cloud)
    d.ellipse([int(140 * s), int(100 * s), int(224 * s), int(184 * s)], fill=cloud)
    d.ellipse([int(52 * s), int(142 * s), int(118 * s), int(208 * s)], fill=cloud)
    d.rounded_rectangle([int(52 * s), int(160 * s), int(224 * s), int(208 * s)], radius=int(24 * s), fill=cloud)
    return img


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "SkyMate.ico"
    draw().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon written to", out)
