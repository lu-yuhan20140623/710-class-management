"""生成增量更新包（renew）：只包含相对上一版本发生变化的业务代码。

用法：
    python make_renew.py --old ..\\v2.0.0\\version.json
    python make_renew.py --old old_version.json --dist dist

前提：先用 build_exe.py 打出新版本的 dist/（含 version.json）。

产物：
    dist/renew_<旧版本>_to_<新版本>.zip
        patch.json     基准哈希、变更/新增/删除清单、逐文件 sha256
        version.json   新版本的完整清单
        app/*.py       仅变化的业务代码

发布时把这个 zip 传到 Gitee Release，并把 sha256 填进 update/latest.json 的 renew 字段。
如果改动范围很大（例如 UI 重构），可以不发布 renew，让客户端直接下载 setup。
"""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
BIG_CHANGE_RATIO = 0.6      # 改动超过 60% 的文件时，提示“建议改用完整安装包”


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.exit(f"读取清单失败：{path}（{exc}）")
    if not isinstance(data.get("files"), dict) or not data.get("version"):
        sys.exit(f"清单格式不正确：{path}")
    return data


def file_map(manifest: dict) -> dict:
    """{文件名: sha256}，兼容 files 值是字符串或 {sha256,size} 两种格式。"""
    result = {}
    for name, info in manifest["files"].items():
        result[name] = info if isinstance(info, str) else info.get("sha256", "")
    return result


def main():
    parser = argparse.ArgumentParser(description="生成 renew 增量更新包")
    parser.add_argument("--old", required=True, help="上一版本的 version.json")
    parser.add_argument("--dist", default=str(ROOT / "dist"), help="新版本打包目录")
    parser.add_argument("--out", default="", help="输出目录（默认与 dist 相同）")
    parser.add_argument("--exe-unchanged", action="store_true",
                        help="启动器未改时强制标记 exe_changed=false（重新打包会改变 exe 哈希）")
    args = parser.parse_args()

    old = load_manifest(Path(args.old))
    dist = Path(args.dist)
    new_path = dist / "version.json"
    if not new_path.exists():
        sys.exit(f"找不到新版本清单：{new_path}（请先运行 build_exe.py）")
    new = load_manifest(new_path)

    old_ver, new_ver = old["version"], new["version"]
    if old_ver == new_ver:
        sys.exit(f"新旧版本相同（{new_ver}），无需生成补丁")

    old_files, new_files = file_map(old), file_map(new)
    changed = sorted(n for n in new_files if n in old_files and new_files[n] != old_files[n])
    added = sorted(n for n in new_files if n not in old_files)
    removed = sorted(n for n in old_files if n not in new_files)
    touched = changed + added

    if not touched and not removed:
        sys.exit("两个版本的代码完全一致，无需生成补丁")

    exe_changed = (old.get("exe") or {}) != (new.get("exe") or {})
    if args.exe_unchanged:
        exe_changed = False
    ratio = len(touched) / max(1, len(new_files))
    if ratio > BIG_CHANGE_RATIO:
        print(f"[提示] 变动文件 {len(touched)}/{len(new_files)}（{ratio:.0%}），改动较大，"
              f"建议本次不发布 renew，直接下发完整安装包。")

    patch = {
        "base_hash": old.get("bundle_hash", ""),
        "version": new_ver,
        "previous_version": old_ver,
        "changed": changed,
        "added": added,
        "removed": removed,
        "files": {n: new_files[n] for n in touched},
        "exe_changed": exe_changed,
    }

    out_dir = Path(args.out) if args.out else dist
    out_dir.mkdir(parents=True, exist_ok=True)
    out_zip = out_dir / f"renew_{old_ver}_to_{new_ver}.zip"

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("patch.json", json.dumps(patch, ensure_ascii=False, indent=2))
        z.write(new_path, "version.json")
        for name in touched:
            z.write(dist / "app" / name, f"app/{name}")

    digest = sha256_file(out_zip)
    size_kb = out_zip.stat().st_size / 1024
    print(f"\n补丁已生成：{out_zip}")
    print(f"  版本：{old_ver} → {new_ver}")
    print(f"  变更 {len(changed)} / 新增 {len(added)} / 删除 {len(removed)}"
          f"  ·  exe 有更新：{'是' if exe_changed else '否'}")
    print(f"  大小：{size_kb:.1f} KB")
    print(f"  sha256：{digest}")
    print("\n把下面的内容合并进 update/latest.json：")
    print(json.dumps({
        "version": new_ver,
        "previous_version": old_ver,
        "exe_changed": exe_changed,
        "renew": {
            "url": f"https://gitee.com/lu-yuhan20140623/710/releases/download/v{new_ver}/{out_zip.name}",
            "sha256": digest,
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
