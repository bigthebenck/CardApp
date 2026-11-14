# PyInstaller build of the app as a folder (dist/CardApp), which installer/CardApp.iss
# packs into CardApp-Setup-<version>.exe. Build with: pyinstaller CardApp.spec

a = Analysis(
    ["run_app.py"],
    datas=[("shuffle_solver/ui/card_images", "shuffle_solver/ui/card_images")],
    # Qt pieces the app never uses, to keep the installer small.
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
)
# Files PySide6's hooks bring along that a widgets-only app never loads: software
# OpenGL, Qt Quick/QML (pulled in by the virtual keyboard plugin), PDF, translations.
_UNUSED = ("opengl32sw", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard",
           "qtvirtualkeyboard", "qpdf", "translations")
a.binaries = [b for b in a.binaries if not any(u in b[0] for u in _UNUSED)]
a.datas = [d for d in a.datas if not any(u in d[0] for u in _UNUSED)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CardApp", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="CardApp")
