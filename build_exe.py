"""PyInstaller 打包：生成解耦的多文件运行目录。

产物结构（dist/）：
    ClassSchedule.exe            启动器（加载 app/main.py，无控制台）
    ClassSchedule_Backend.exe    启动器（加载 app/backend_service.py，无控制台）
    ClassSchedule_Overlay.exe    启动器（加载 app/overlay_window.py，无控制台）
    ClassSchedule_Ball.exe       启动器（加载 app/floating_ball_service.py，无控制台）
    app/*.py                     业务代码，补丁可按文件替换
    version.json                 版本号 + 每个文件 sha256 + 整包哈希

业务代码不打进 exe，因此修改代码后只需替换 app/ 下对应文件即可。
四个 exe 均为窗口模式（--noconsole），启动器把 print 重定向到 logs/*.log。
"""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DIST = ROOT / "dist"
BUILD = ROOT / "build"

CLEAN = "--clean" in sys.argv or "-c" in sys.argv

# 需要随包发布的业务代码（顺序无关）
APP_FILES = [
    "main.py",
    "ui.py",
    "backend.py",
    "backend_service.py",
    "overlay_window.py",
    "schedule.py",
    "auth.py",
    "autostart.py",
    "time_debug.py",
    "student_score.py",
    "hygiene.py",
    "score_records.py",
    "charts.py",
    "floating_ball.py",
    "floating_ball_service.py",
    "ball_bridge.py",
    "plugin_events.py",
    "plugin_api.py",
    "version.py",
    "version_manager.py",
    "updater.py",
]

# 随包发布的默认名单（班级 / 学生 / 分组），安装后无需重新录入
DATA_FILES = [
    "class_data.txt",
    "student_data.txt",
    "group_data.txt",
]

# (exe 名, 启动器, 是否隐藏控制台) —— 全部窗口模式，不弹黑色控制台
SPECS = [
    ("ClassSchedule", "launcher_main.py", True),
    ("ClassSchedule_Backend", "launcher_backend.py", True),
    ("ClassSchedule_Overlay", "launcher_overlay.py", True),
    ("ClassSchedule_Ball", "launcher_ball.py", True),
]

LAUNCHERS = [s[1] for s in SPECS]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def bundle_hash(files: dict) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(f"{name}\0{files[name]}\n".encode("utf-8"))
    return h.hexdigest()


def local_module_names() -> set:
    return {Path(f).stem for f in APP_FILES + LAUNCHERS}


def collect_hidden_imports() -> list:
    """扫描业务代码的 import，补进 exe，避免启动时缺标准库/子模块。"""
    local = local_module_names()
    mods = set()
    for name in APP_FILES:
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mods.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
                if node.module == "tkinter":
                    for alias in node.names:
                        mods.add(f"tkinter.{alias.name}")
    mods -= local
    mods |= {
        "tkinter", "tkinter.ttk", "tkinter.messagebox",
        "tkinter.simpledialog", "tkinter.filedialog",
        # 归档 XLSX 用（不会自动被 PyInstaller 完整收集）
        "openpyxl", "openpyxl.workbook", "openpyxl.worksheet",
        "openpyxl.styles", "openpyxl.utils", "et_xmlfile",
        # 悬浮球图片皮肤用（plugins/assets/*.png 裁圆）
        "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageOps", "PIL.ImageTk",
    }
    return sorted(mods)


def build_exe(exe_name: str, entry: str, noconsole: bool, hidden: list):
    print(f"\n{'=' * 60}")
    print(f"打包 {exe_name}  ←  {entry}")
    print(f"{'=' * 60}")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        f"--name={exe_name}",
        "--onefile",
        f"--distpath={DIST}",
        f"--workpath={BUILD}",
        f"--specpath={BUILD}",
        "--noconfirm",
        "--collect-submodules=tkinter",
        "--collect-submodules=openpyxl",
    ]
    if noconsole:
        cmd.append("--noconsole")
    for m in hidden:
        cmd.append(f"--hidden-import={m}")
    # 业务代码必须从 app/ 加载，禁止打进 exe
    for m in sorted(local_module_names()):
        cmd.append(f"--exclude-module={m}")
    cmd.append(str(ROOT / entry))

    print("  命令:", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        print(f"[失败] {exe_name}")
        sys.exit(1)
    print(f"[完成] {exe_name}")


def main():
    if CLEAN:
        for d in (DIST, BUILD):
            if d.exists():
                shutil.rmtree(d)
        print("已清理旧产物")

    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    hidden = collect_hidden_imports()

    for exe_name, entry, noconsole in SPECS:
        build_exe(exe_name, entry, noconsole, hidden)

    # 发布业务代码
    app_dir = DIST / "app"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    for name in APP_FILES:
        shutil.copy2(ROOT / name, app_dir / name)

    # 插件目录：保持目录结构发布（运行期自动扫描，不进 version.json 补丁清单）
    plugin_src = ROOT / "plugins"
    if plugin_src.is_dir():
        plugin_dst = DIST / "plugins"
        if plugin_dst.exists():
            shutil.rmtree(plugin_dst)
        shutil.copytree(plugin_src, plugin_dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data"))
        print(f"  发布插件：{len(list(plugin_dst.rglob('*.py')))} 个文件")

    # 默认名单：目标目录已有数据时不覆盖，避免升级冲掉真实积分
    for name in DATA_FILES:
        src = ROOT / name
        if not src.exists():
            continue
        dst = DIST / name
        if dst.exists():
            print(f"  保留已有数据 {name}")
            continue
        if name in ("group_data.txt", "student_data.txt"):
            # 默认名单只带结构，积分清零，不带开发时的测试记录
            try:
                data = json.loads(src.read_text(encoding="utf-8"))
                if name == "group_data.txt":
                    for groups in data.values():
                        for group in groups.values():
                            group["total_score"] = 0
                            group["record"] = []
                else:
                    for students in data.values():
                        for stu in students.values():
                            stu["records"] = []
                            stu["total_score"] = 0
                dst.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                print(f"  预置默认名单 {name}（积分已归零）")
                continue
            except Exception as exc:
                print(f"  [警告] 处理 {name} 失败，改为原样复制：{exc}")
        shutil.copy2(src, dst)
        print(f"  预置默认名单 {name}")

    sys.path.insert(0, str(ROOT))
    from version import VERSION

    files = {}
    for name in APP_FILES:
        p = app_dir / name
        files[name] = {"sha256": sha256_file(p), "size": p.stat().st_size}

    exe_hashes = {
        p.name: sha256_file(p) for p in sorted(DIST.glob("*.exe"))
    }
    flat = {name: info["sha256"] for name, info in files.items()}

    manifest = {
        "version": VERSION,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "bundle_hash": bundle_hash(flat),
        "files": files,
        "exe": exe_hashes,
    }
    (DIST / "version.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"打包完成：{VERSION}")
    print(f"产物目录：{DIST}")
    print(f"代码文件：{len(files)} 个")
    print(f"整包哈希：{manifest['bundle_hash']}")
    for f in sorted(DIST.glob("*.exe")):
        mb = f.stat().st_size / 1024 / 1024
        print(f"  {f.name:30s} {mb:7.1f} MB")
    print(f"  {'app/*.py':30s} {sum(i['size'] for i in files.values()) / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
