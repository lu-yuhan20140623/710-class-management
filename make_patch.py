"""生成版本补丁包（开发者工具）。

用法：
    python make_patch.py --old <旧版 dist 目录> --new <新版 dist 目录> [--out 补丁.zip]

补丁内包含：
    patch.json    基准/目标哈希、变更文件列表
    version.json  目标版本清单
    app/*.py      目标版本的完整代码（哈希不匹配时用于整目录替换）
"""
import argparse
import json
import sys
import time
import zipfile
from pathlib import Path


def load_manifest(dist: Path) -> dict:
    p = dist / "version.json"
    if not p.exists():
        sys.exit(f"缺少版本清单：{p}")
    return json.loads(p.read_text(encoding="utf-8"))


def files_of(manifest: dict) -> dict:
    result = {}
    for name, info in manifest.get("files", {}).items():
        result[name] = info.get("sha256", "") if isinstance(info, dict) else info
    return result


def main():
    ap = argparse.ArgumentParser(description="生成课程表版本补丁")
    ap.add_argument("--old", required=True, help="旧版 dist 目录（含 version.json）")
    ap.add_argument("--new", required=True, help="新版 dist 目录（含 version.json）")
    ap.add_argument("--out", default="", help="输出补丁 zip 路径")
    args = ap.parse_args()

    old_dir = Path(args.old).resolve()
    new_dir = Path(args.new).resolve()
    old_m = load_manifest(old_dir)
    new_m = load_manifest(new_dir)
    old_files = files_of(old_m)
    new_files = files_of(new_m)

    changed = sorted(n for n in new_files if n in old_files and new_files[n] != old_files[n])
    added = sorted(n for n in new_files if n not in old_files)
    removed = sorted(n for n in old_files if n not in new_files)

    old_exe = old_m.get("exe", {})
    new_exe = new_m.get("exe", {})
    exe_changed = sorted(n for n, h in new_exe.items() if old_exe.get(n) != h)

    if not (changed or added or removed):
        print("两个版本代码完全一致，无需生成补丁。")
        return

    out = Path(args.out) if args.out else Path(
        f"patch_{old_m.get('version')}_to_{new_m.get('version')}.zip")

    patch = {
        "base_version": old_m.get("version"),
        "base_hash": old_m.get("bundle_hash"),
        "target_version": new_m.get("version"),
        "target_hash": new_m.get("bundle_hash"),
        "changed": changed,
        "added": added,
        "removed": removed,
        "files": new_files,
        "exe_changed": exe_changed,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("patch.json", json.dumps(patch, ensure_ascii=False, indent=2))
        z.write(new_dir / "version.json", "version.json")
        for name in sorted(new_files):
            src = new_dir / "app" / name
            if not src.exists():
                sys.exit(f"新版目录缺少代码文件：{src}")
            z.write(src, f"app/{name}")

    print(f"补丁已生成：{out}")
    print(f"  {patch['base_version']} → {patch['target_version']}")
    print(f"  变更 {len(changed)} / 新增 {len(added)} / 删除 {len(removed)}")
    if exe_changed:
        print("  注意：exe 有变化，建议同时提供完整安装包：" + "、".join(exe_changed))


if __name__ == "__main__":
    main()
