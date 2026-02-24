# -*- coding: utf-8 -*-
import os
import sys
from PIL import Image

def overlay_images(background_path, overlay_path, output_path, transparency=128):
    try:
        background_path = os.path.normpath(background_path)
        overlay_path = os.path.normpath(overlay_path)
        output_path = os.path.normpath(output_path)

        print(f"[INFO] 加载原图: {background_path}")
        background = Image.open(background_path).convert("RGBA")

        print(f"[INFO] 加载剂量图: {overlay_path}")
        overlay = Image.open(overlay_path).convert("RGBA")

        overlay = overlay.resize(background.size)
        result = Image.blend(background, overlay, transparency / 255.0)

        result.save(output_path)
        print(f"[SUCCESS] 合成图像保存到: {output_path}")
    except Exception as e:
        print(f"[ERROR] 合成失败: {e}", file=sys.stderr)

def main():
    args = sys.argv
    if len(args) == 4:
        # 单张合成模式
        background_path = args[1]
        overlay_path = args[2]
        output_path = args[3]
        print(f"[MODE] 单张合成模式")
        overlay_images(background_path, overlay_path, output_path)
    else:
        print("用法: python doseplus.py <原图> <剂量图> <输出路径>")

if __name__ == "__main__":
    main()
