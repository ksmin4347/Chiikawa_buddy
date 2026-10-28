# Run from the project root: python -m PyInstaller --noconfirm DesktopBuddy.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'desktop_buddy_entry.py')],
    pathex=[str(root / 'src')],
    datas=[(str(root / 'assets'), 'assets')] + collect_data_files('tzdata'),
    hiddenimports=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtPdf', 'tkinter', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='DesktopBuddy',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    icon=str(root / 'assets' / 'icons' / 'buddy.ico'),
    version=str(root / 'tools' / 'windows_version.txt'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DesktopBuddy')
