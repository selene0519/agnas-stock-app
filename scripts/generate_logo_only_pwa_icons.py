"""Generate launch icons that show only the MONE mark without visible corners."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "mone-web-app" / "frontend" / "public"
SOURCE = PUBLIC / "loading" / "mone-logo.png"
SPLASH_BACKGROUND = (11, 18, 32, 255)


def _centered_logo(
    size: int,
    width_ratio: float,
    background: tuple[int, int, int, int],
) -> Image.Image:
    source = Image.open(SOURCE).convert("RGBA")
    alpha_box = source.getchannel("A").getbbox()
    if alpha_box is None:
        raise ValueError(f"Logo has no visible pixels: {SOURCE}")

    source = source.crop(alpha_box)
    target_width = round(size * width_ratio)
    target_height = round(target_width * source.height / source.width)
    logo = source.resize((target_width, target_height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (size, size), background)
    position = ((size - target_width) // 2, (size - target_height) // 2)
    canvas.alpha_composite(logo, position)
    return canvas


def main() -> None:
    icons = PUBLIC / "icons"
    icons.mkdir(parents=True, exist_ok=True)

    for size in (192, 512):
        _centered_logo(size, 0.78, (0, 0, 0, 0)).save(
            icons / f"splash-logo-v2-{size}.png", optimize=True
        )
        _centered_logo(size, 0.58, SPLASH_BACKGROUND).save(
            icons / f"splash-maskable-v2-{size}.png", optimize=True
        )

    _centered_logo(180, 0.62, SPLASH_BACKGROUND).save(
        icons / "apple-touch-logo-v2.png", optimize=True
    )


if __name__ == "__main__":
    main()
