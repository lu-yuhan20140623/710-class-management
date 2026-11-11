"""版本与代码哈希：识别安装版本、校验代码完整性、为补丁提供依据。

打包产物 version.json 记录每个代码文件的 sha256 以及整包哈希（bundle_hash），
补丁以 bundle_hash 作为「基准版本」判断是否可以直接增量替换。
"""
import hashlib
import json
import sys
from pathlib import Path

from version import VERSION

APP_SUBDIR = "app"
MANIFEST_NAME = "version.json"


def base_dir() -> Path:
    """安装目录：打包后为 exe 所在目录，开发时为源码目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


def app_dir() -> Path:
    """业务代码目录：打包后为 <安装目录>/app，开发时回退到源码目录。"""
    d = base_dir() / APP_SUBDIR
    return d if d.is_dir() else base_dir()


def manifest_path() -> Path:
    return base_dir() / MANIFEST_NAME


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def bundle_hash(files: dict) -> str:
    """整包哈希：文件名 + 文件哈希按名称排序后整体 sha256。"""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(f"{name}\0{files[name]}\n".encode("utf-8"))
    return h.hexdigest()


def load_manifest():
    p = manifest_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def manifest_files(manifest) -> dict:
    """兼容两种写法：{"a.py": "hash"} 或 {"a.py": {"sha256": "hash"}}。"""
    result = {}
    for name, info in (manifest or {}).get("files", {}).items():
        result[name] = info.get("sha256", "") if isinstance(info, dict) else info
    return result


def scan_code() -> dict:
    return {p.name: sha256_file(p) for p in sorted(app_dir().glob("*.py"))}


def status() -> dict:
    manifest = load_manifest()
    current = scan_code()
    current_hash = bundle_hash(current)

    if manifest is None:
        return {
            "packaged": False,
            "version": VERSION,
            "current_hash": current_hash,
            "files": current,
            "matches": None,
            "modified": [],
            "missing": [],
            "extra": [],
            "exe_changed": [],
        }

    expected = manifest_files(manifest)
    modified = sorted(n for n in expected if n in current and current[n] != expected[n])
    missing = sorted(n for n in expected if n not in current)
    extra = sorted(n for n in current if n not in expected)
    exe_changed = sorted(
        name for name, h in (manifest.get("exe") or {}).items()
        if not (base_dir() / name).exists() or sha256_file(base_dir() / name) != h
    )
    return {
        "packaged": True,
        "version": manifest.get("version", VERSION),
        "bundle_hash": manifest.get("bundle_hash", ""),
        "current_hash": current_hash,
        "files": current,
        "matches": not modified and not missing and current_hash == manifest.get("bundle_hash"),
        "modified": modified,
        "missing": missing,
        "extra": extra,
        "exe_changed": exe_changed,
    }


def describe() -> str:
    st = status()
    lines = [f"课程表 {st['version']}", f"安装目录：{base_dir()}"]

    if not st["packaged"]:
        lines.append("代码校验：未打包（开发模式，无 version.json）")
        lines.append(f"当前代码哈希：{st['current_hash']}")
        return "\n".join(lines)

    if st["matches"]:
        lines.append(f"代码校验：通过（{st['version']}）")
    else:
        lines.append("代码校验：未通过（文件被修改或缺失）")
        if st["modified"]:
            lines.append("  已修改：" + "、".join(st["modified"]))
        if st["missing"]:
            lines.append("  缺失：" + "、".join(st["missing"]))
        if st["extra"]:
            lines.append("  额外：" + "、".join(st["extra"]))

    lines.append(f"整包哈希：{st['current_hash']}")
    if st.get("bundle_hash") and st["bundle_hash"] != st["current_hash"]:
        lines.append(f"发布哈希：{st['bundle_hash']}")

    if st["exe_changed"]:
        lines.append("运行文件：有更新（" + "、".join(st["exe_changed"]) + "）")
    else:
        lines.append("运行文件：一致")

    return "\n".join(lines)
