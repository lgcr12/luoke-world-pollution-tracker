from pathlib import Path

try:
    from PIL import ImageGrab
except Exception:
    print("缺少 Pillow，请先安装: python -m pip install pillow")
    raise SystemExit(1)


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "assets" / "pollution_icon.png"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = ImageGrab.grabclipboard()
    if img is None:
        print("剪贴板里没有图片。请先复制污染图标图片，然后再运行本脚本。")
        raise SystemExit(1)

    # 有时返回文件路径列表，而不是图像对象
    if isinstance(img, list):
        for p in img:
            pp = Path(p)
            if pp.exists() and pp.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                from PIL import Image
                with Image.open(pp) as im:
                    im.save(OUT)
                print(f"已保存模板图: {OUT}")
                return
        print("剪贴板包含文件，但不是图片文件。")
        raise SystemExit(1)

    # 直接是图像对象
    img.save(OUT)
    print(f"已保存模板图: {OUT}")


if __name__ == "__main__":
    main()

