"""补丁应用工具。

用法：
    ClassSchedule.exe --apply-patch 补丁.zip

规则：
  * 当前代码哈希 == 补丁的基准哈希 → 只替换发生变化的文件（增量更新）；
  * 哈希对不上（文件被改过 / 版本不同）→ 整目录替换补丁内全部代码；
  * 更新后逐个文件校验 sha256，并写入新的 version.json。
"""
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import version_manager as vm


def _copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def apply_patch(patch_path) -> tuple:
    if not getattr(sys, "frozen", False):
        return False, "请在安装目录运行：ClassSchedule.exe --apply-patch <补丁.zip>"

    src_zip = Path(patch_path)
    if not src_zip.exists():
        return False, f"补丁文件不存在：{src_zip}"

    tmp = Path(tempfile.mkdtemp(prefix="cs_patch_"))
    backup = Path(tempfile.mkdtemp(prefix="cs_backup_"))
    target = vm.app_dir()
    target.mkdir(parents=True, exist_ok=True)
    old_manifest = vm.manifest_path()

    try:
        with zipfile.ZipFile(src_zip) as z:
            z.extractall(tmp)

        patch_file = tmp / "patch.json"
        payload = tmp / "app"
        new_manifest = tmp / "version.json"
        if not patch_file.exists() or not payload.is_dir() or not new_manifest.exists():
            return False, "补丁格式错误：需要 patch.json、version.json 和 app/ 目录"

        patch = json.loads(patch_file.read_text(encoding="utf-8"))
        before = vm.status()
        incremental = before.get("current_hash") == patch.get("base_hash")

        # 备份当前代码与清单，校验失败时回滚
        for f in target.glob("*.py"):
            shutil.copy2(f, backup / f.name)
        if old_manifest.exists():
            shutil.copy2(old_manifest, backup / vm.MANIFEST_NAME)

        try:
            if incremental:
                names = set(patch.get("changed", [])) | set(patch.get("added", []))
                for name in names:
                    if (payload / name).exists():
                        _copy(payload / name, target / name)
                for name in patch.get("removed", []):
                    (target / name).unlink(missing_ok=True)
            else:
                keep = {f.name for f in payload.glob("*.py")}
                for name in keep:
                    _copy(payload / name, target / name)
                for f in target.glob("*.py"):
                    if f.name not in keep:
                        f.unlink()

            expected = patch.get("files", {})
            bad = [name for name, h in expected.items()
                   if not (target / name).exists()
                   or vm.sha256_file(target / name) != h]
            if bad:
                raise RuntimeError("文件校验失败：" + "、".join(bad))

            _copy(new_manifest, old_manifest)
        except Exception:
            for f in target.glob("*.py"):
                f.unlink()
            for f in backup.glob("*.py"):
                shutil.copy2(f, target / f.name)
            if (backup / vm.MANIFEST_NAME).exists():
                shutil.copy2(backup / vm.MANIFEST_NAME, old_manifest)
            raise

        after = vm.status()
        mode = "增量更新" if incremental else "整包替换"
        lines = [f"补丁应用成功（{mode}）：{before.get('version') or '未知'} → {after.get('version')}"]
        if patch.get("exe_changed"):
            lines.append("注意：运行文件（exe）也有更新，代码已替换，建议使用完整安装包覆盖 exe。")
        if not after.get("matches"):
            lines.append("警告：更新后校验未通过，请使用完整安装包重新安装。")
        return True, "\n".join(lines)

    except Exception as exc:
        return False, f"补丁应用失败：{exc}\n请使用完整安装包覆盖。"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
