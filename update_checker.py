"""在线更新：检查 Gitee 版本清单、自动选择 renew 补丁或完整安装包、后台下载。

清单放在仓库 update/latest.json（raw 地址），格式：

    {
      "version": "2.1.0",
      "published_at": "2026-11-20",
      "previous_version": "2.0.0",
      "exe_changed": false,
      "notes": "本次更新内容……",
      "release_url": "https://gitee.com/<用户>/<仓库>/releases/tag/v2.1.0",
      "renew": {"url": "https://…/renew_2.0.0_to_2.1.0.zip", "sha256": "…"},
      "setup": {"url": "https://…/ClassSchedule_Setup_2.1.0.exe", "sha256": "…"}
    }

选择规则：
  * 当前版本 == previous_version 且 renew 存在且 exe 未变 → 下载 renew（只含改动文件）
  * 其他情况（跨版本、renew 缺失、exe 有更新）→ 下载 setup 完整安装包

设计约束：
  * 只使用标准库，打包后不引入新依赖
  * 任何网络/校验失败都保持静默，不影响正常启动；只有真正要应用更新时才提示
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from version import VERSION

REPO = "lu-yuhan20140623/710"
MANIFEST_URL = f"https://gitee.com/{REPO}/raw/master/update/latest.json"
CHECK_INTERVAL = 6 * 3600      # 每 6 小时最多检查一次
HTTP_TIMEOUT = 10
MAX_DOWNLOAD = 300 * 1024 * 1024


# ---------------- 路径 ----------------
def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


def updates_dir() -> Path:
    d = base_dir() / "updates"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        # 安装目录不可写（例如装在 Program Files）时退到用户目录
        d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ClassSchedule" / "updates"
        d.mkdir(parents=True, exist_ok=True)
        return d


def state_path() -> Path:
    return base_dir() / "update_state.json"


def pending_path() -> Path:
    return updates_dir() / "pending.json"


# ---------------- 小工具 ----------------
def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def version_tuple(text: str) -> tuple:
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(version: str) -> bool:
    return version_tuple(version) > version_tuple(VERSION)


def manifest_url() -> str:
    """settings.json 里的 update_manifest 可覆盖默认地址（便于内网/调试）。"""
    settings = _read_json(base_dir() / "settings.json", {})
    url = (settings or {}).get("update_manifest")
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else MANIFEST_URL


def _state() -> dict:
    data = _read_json(state_path(), {})
    return data if isinstance(data, dict) else {}


def _save_state(**kw):
    data = _state()
    data.update(kw)
    _write_json(state_path(), data)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------- 检查 ----------------
def fetch_manifest() -> dict | None:
    """读取远程清单；任何异常都返回 None。"""
    req = urllib.request.Request(
        manifest_url(),
        headers={"User-Agent": f"ClassSchedule/{VERSION}", "Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read(1 << 20)
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("version"):
        return None
    return data


def check(force: bool = False) -> dict | None:
    """有新版本时返回清单，否则 None。默认 6 小时内不重复请求。"""
    now = time.time()
    st = _state()
    if not force and now - float(st.get("last_check", 0)) < CHECK_INTERVAL:
        return None
    manifest = fetch_manifest()
    _save_state(last_check=now)
    if manifest is None or not is_newer(manifest["version"]):
        return None
    return manifest


def choose_kind(manifest: dict) -> str | None:
    """renew（增量）或 setup（完整包）。"""
    setup = manifest.get("setup") or {}
    renew = manifest.get("renew") or {}
    same_as_previous = (
        manifest.get("previous_version") == VERSION
        and bool(renew.get("url")) and bool(renew.get("sha256"))
    )
    if same_as_previous and not manifest.get("exe_changed"):
        return "renew"
    if setup.get("url") and setup.get("sha256"):
        return "setup"
    if same_as_previous:          # 没提供完整包时，增量仍可用
        return "renew"
    return None


# ---------------- 下载 ----------------
def _download(url: str, dest: Path, expect_sha: str) -> tuple:
    if expect_sha and len(expect_sha) != 64:
        return False, "清单里的 sha256 无效（可能还没上传附件）"
    tmp = dest.with_suffix(dest.suffix + ".part")
    got = hashlib.sha256()
    size = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"ClassSchedule/{VERSION}"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise RuntimeError("安装包超过 300MB，已中止")
                got.update(chunk)
                f.write(chunk)
        if expect_sha and got.hexdigest() != expect_sha:
            raise RuntimeError("sha256 校验失败，文件可能损坏")
        os.replace(tmp, dest)
        return True, ""
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False, str(exc)


def prepare(manifest: dict) -> tuple:
    """按清单下载合适的更新文件，并写入 pending.json。"""
    kind = choose_kind(manifest)
    if not kind:
        return False, "清单里没有可用的下载地址"
    item = manifest.get(kind) or {}
    version = str(manifest["version"])
    suffix = ".zip" if kind == "renew" else ".exe"
    dest = updates_dir() / f"{version}_{kind}{suffix}"
    if dest.exists() and sha256_file(dest) == item.get("sha256"):
        ok, err = True, ""
    else:
        ok, err = _download(item["url"], dest, item.get("sha256", ""))
        if not ok and item.get("fallback_url"):
            # 主通道（Gitee Release）没找到对应版本或下载失败，退回官网自建下载
            ok, err = _download(item["fallback_url"], dest, item.get("sha256", ""))
    if not ok:
        return False, f"下载{('补丁' if kind == 'renew' else '安装包')}失败：{err}"
    _write_json(pending_path(), {
        "version": version,
        "kind": kind,
        "path": str(dest),
        "sha256": item.get("sha256", ""),
        "notes": manifest.get("notes", ""),
        "release_url": manifest.get("release_url", ""),
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return True, f"已下载 {version}（{kind}）"


def auto_check_background() -> tuple:
    """后台（开机自启的 backend）调用：检查 + 下载，失败静默。"""
    try:
        pending = load_pending()
        if pending:
            return True, f"已有待安装更新 {pending.get('version')}"
        manifest = check()
        if not manifest:
            return False, "暂无更新"
        return prepare(manifest)
    except Exception as exc:
        return False, f"检查更新异常：{exc}"


# ---------------- 待安装 ----------------
def load_pending() -> dict | None:
    try:
        data = _read_json(pending_path(), None)
    except OSError:
        return None
    if not isinstance(data, dict):
        return None
    path = Path(str(data.get("path", "")))
    if not path.exists() or not is_newer(str(data.get("version", ""))):
        return None
    return data


def clear_pending():
    try:
        pending_path().unlink(missing_ok=True)
    except OSError:
        pass


def manual_download_hint(pending: dict | None = None) -> str:
    url = (pending or {}).get("release_url") or ""
    if not url:
        data = _state()
        url = data.get("release_url") or f"https://gitee.com/{REPO}/releases"
    return url
