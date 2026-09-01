# -*- coding: utf-8 -*-
"""
images/ 图片批量优化脚本
- 遍历 images/ 下所有子文件夹的 .jpg/.jpeg/.png
- 转换为 Google 推荐的 WebP 格式,质量从 85% 起步
- 若单张超过 200KB,自动阶梯降质(每次 -5,最低 40)直到 <=200KB
- 原图先镜像备份到 _images_backup/(仓库外,便于回滚)
- 转换成功后删除原 .jpg/.png(实现"覆盖原图")
"""
import os
import sys
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "images"
BACKUP_DIR = ROOT / "_images_backup"
MAX_BYTES = 200 * 1024          # 200KB
START_QUALITY = 85
MIN_QUALITY = 40
STEP = 5
EXTS = {".jpg", ".jpeg", ".png"}


def convert_to_webp(src: Path) -> dict:
    """转换单张图片,返回统计信息。"""
    info = {"name": src.name, "rel": str(src.relative_to(IMG_DIR))}
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)  # 修正 EXIF 方向
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA") if "A" in im.mode else im.convert("RGB")
        else:
            im = im.convert("RGB")

        target = src.with_suffix(".webp")
        quality = START_QUALITY
        best_quality = quality
        best_size = None
        tmp = target.with_suffix(".webp.tmp")
        # 先求满足 <=200KB 的最高质量
        while True:
            im.save(tmp, "WEBP", quality=quality, method=6)
            size = tmp.stat().st_size
            if size <= MAX_BYTES or quality <= MIN_QUALITY:
                best_quality, best_size = quality, size
                break
            quality -= STEP

        # 若最低质量仍超限,回扫保留最小体积的一档
        if best_size > MAX_BYTES:
            best_quality, best_size = MIN_QUALITY, None
            for q in range(MIN_QUALITY, START_QUALITY + 1, STEP):
                im.save(tmp, "WEBP", quality=q, method=6)
                s = tmp.stat().st_size
                if best_size is None or s < best_size:
                    best_size, best_quality = s, q

    tmp.replace(target)  # 原子覆盖
    info.update({
        "quality": best_quality,
        "orig_bytes": src.stat().st_size,
        "new_bytes": best_size,
        "saved_pct": round((1 - best_size / src.stat().st_size) * 100, 1) if src.stat().st_size else 0,
        "over_limit": best_size > MAX_BYTES,
        "webp": target.name,
    })
    return info


def main():
    imgs = sorted(
        p for p in IMG_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in EXTS
    )
    if not imgs:
        print("未找到任何 .jpg/.jpeg/.png 图片。")
        return

    print(f"共发现 {len(imgs)} 张图片,开始转换...\n")
    results, fails = [], []
    total_old = total_new = 0

    for src in imgs:
        try:
            # 1) 备份原图(镜像目录结构,保留扩展名)
            rel = src.relative_to(IMG_DIR)
            bak = BACKUP_DIR / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            if not bak.exists():
                bak.write_bytes(src.read_bytes())

            # 2) 转换
            info = convert_to_webp(src)
            # 3) 覆盖:删除原图
            src.unlink()
            results.append(info)
            total_old += info["orig_bytes"]
            total_new += info["new_bytes"]
            flag = "  [>200KB]" if info["over_limit"] else ""
            print(f"  {info['rel']:<50} q={info['quality']:>3}  "
                  f"{info['orig_bytes']/1024:8.1f}KB -> {info['new_bytes']/1024:7.1f}KB  "
                  f"省 {info['saved_pct']:5.1f}%{flag}")
        except Exception as e:  # noqa: BLE001
            fails.append((str(src), str(e)))
            print(f"  FAIL {src}: {e}")

    print("\n========== 汇总 ==========")
    print(f"成功转换: {len(results)} 张")
    if fails:
        print(f"失败: {len(fails)} 张")
        for f, e in fails:
            print(f"  - {f}: {e}")
    if results:
        print(f"总大小: {total_old/1024:.1f}KB -> {total_new/1024:.1f}KB "
              f"(节省 {100*(1-total_new/total_old):.1f}%)")
        over = [r for r in results if r["over_limit"]]
        if over:
            print(f"警告: {len(over)} 张即使降到质量 {MIN_QUALITY} 仍 >200KB:")
            for r in over:
                print(f"  - {r['rel']}: {r['new_bytes']/1024:.1f}KB (q={r['quality']})")
        else:
            print("全部图片均已压至 200KB 以下。")
    print(f"\n原图备份目录: {BACKUP_DIR}")
    print("完成。可直接删除 _images_backup 释放空间(不建议,留作回滚)。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
