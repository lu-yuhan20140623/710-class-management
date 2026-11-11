"""
PyInstaller 打包脚本：生成 3 个独立 EXE
  ClassSchedule.exe          — main.py（设置面板 + 课程表）
  ClassSchedule_Backend.exe  — backend_service.py（后台常驻，无控制台）
  ClassSchedule_Overlay.exe  — overlay_window.py（倒计时窗口）
"""
import subprocess, sys, os, shutil
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DIST = ROOT / "dist"
BUILD = ROOT / "build"

CLEAN = "--clean" in sys.argv or "-c" in sys.argv

if CLEAN:
    for d in [DIST, BUILD]:
        if d.exists():
            shutil.rmtree(d)
    print("已清理旧产物")

SPECS = [
    # (exe名, 入口脚本, 是否隐藏控制台)
    ("ClassSchedule",         "main.py",           False),
    ("ClassSchedule_Backend", "backend_service.py", True),
    ("ClassSchedule_Overlay", "overlay_window.py",  False),
]

shared_args = [
    "--noconfirm",
    f"--distpath={DIST}",
    f"--workpath={BUILD}",
    f"--specpath={ROOT}",
    "--collect-submodules=tkinter",
    "--hidden-import=student_score",
]

# 所有要一起打包的 .py 数据文件
extra_datas = [
    "auth.py", "schedule.py", "autostart.py", "backend.py",
    "time_debug.py", "ui.py", "student_score.py",
]

for exe_name, entry, noconsole in SPECS:
    print(f"\n{'='*60}")
    print(f"打包 {exe_name}  ←  {entry}")
    print(f"{'='*60}")

    cmd = [sys.executable, "-m", "PyInstaller",
           f"--name={exe_name}",
           "--onefile",
           f"--paths={ROOT}",
           *shared_args]

    if noconsole:
        cmd.append("--noconsole")

    # 把额外 .py 文件作为数据打进去，保证动态 import 能找到
    for f in extra_datas:
        cmd.append(f"--add-data={f}{os.pathsep}.")

    # entry 脚本
    cmd.append(str(ROOT / entry))

    print("  命令:", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        print(f"❌ {exe_name} 打包失败！")
        sys.exit(1)
    print(f"✅ {exe_name} 打包完成")

print(f"\n{'='*60}")
print(f"全部完成！产物在 {DIST}")
for f in sorted(DIST.glob("*.exe")):
    mb = f.stat().st_size / 1024 / 1024
    print(f"  {f.name:35s} {mb:7.1f} MB")
