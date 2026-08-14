import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "mone-web-app" / "frontend"


def test_pre_react_splash_shows_only_the_transparent_logo() -> None:
    layout = (FRONTEND / "app" / "layout.tsx").read_text(encoding="utf-8")
    splash = layout.split('id="mone-html-splash"', 1)[1].split("{children}", 1)[0]

    assert '/icons/splash-logo-v2-512.png?v=3' in splash
    assert 'width={96}' in splash
    assert 'background: "transparent"' in splash
    assert splash.count("<img") == 1
    assert '/loading/mone-bear.png' not in splash


def test_manifest_uses_versioned_logo_only_launch_icons() -> None:
    manifest = json.loads((FRONTEND / "public" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["background_color"] == "#0b1220"
    assert manifest["theme_color"] == "#0b1220"
    assert [icon["src"] for icon in manifest["icons"]] == [
        "/icons/splash-logo-v2-192.png?v=3",
        "/icons/splash-logo-v2-512.png?v=3",
        "/icons/splash-maskable-v2-192.png?v=3",
        "/icons/splash-maskable-v2-512.png?v=3",
    ]


def test_launch_icons_have_no_visible_edge_against_the_splash() -> None:
    public = FRONTEND / "public"
    expected_background = (11, 18, 32, 255)

    for size in (192, 512):
        any_icon = Image.open(
            public / "icons" / f"splash-logo-v2-{size}.png"
        ).convert("RGBA")
        maskable_icon = Image.open(
            public / "icons" / f"splash-maskable-v2-{size}.png"
        ).convert("RGBA")

        assert any_icon.size == (size, size)
        assert any_icon.getpixel((0, 0))[3] == 0
        assert any_icon.getchannel("A").getbbox() is not None
        assert maskable_icon.size == (size, size)
        assert maskable_icon.getpixel((0, 0)) == expected_background

    apple_icon = Image.open(
        public / "icons" / "apple-touch-logo-v2.png"
    ).convert("RGBA")
    assert apple_icon.size == (180, 180)
    assert apple_icon.getpixel((0, 0)) == expected_background
