# PyInstaller build of the app as a folder (dist/CardApp), which installer/CardApp.iss
# packs into CardApp-Setup-<version>.exe. Build with: pyinstaller CardApp.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ["run_app.py"],
    datas=[("shuffle_solver/ui/card_images", "shuffle_solver/ui/card_images"),
           *collect_data_files("ttkbootstrap")],
    hiddenimports=collect_submodules("ttkbootstrap"),
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CardApp", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="CardApp")
