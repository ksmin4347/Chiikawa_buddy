# Run from the project root: python -m PyInstaller --noconfirm DesktopBuddy.spec
import importlib.util
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
runtime_spec = importlib.util.spec_from_file_location('build_runtime', root / 'tools' / 'build_runtime.py')
runtime = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(runtime)
windows = Path(os.environ.get('WINDIR', r'C:\Windows'))
bindings = [Path(importlib.util.find_spec(name).origin).parent for name in ('PySide6', 'shiboken6')]
runtime.configure_build_path(Path(sys.base_prefix), Path(sys.executable).parent, bindings, windows)
a = Analysis(
    [str(root / 'desktop_buddy_entry.py')],
    pathex=[str(root / 'src')],
    datas=[(str(root / 'assets' / 'default_character'), 'assets/default_character'),
           (str(root / 'assets' / 'icons'), 'assets/icons'),
           *[(str(root / 'assets' / 'character_packs' / key / name),
              f'assets/character_packs/{key}')
             for key in ('chiikawa', 'hachiware', 'usagi')
             for name in ('manifest.json', 'atlas.png', 'focus_001.png',
                          'focus_002.png', 'focus_003.png')],
           *[(str(root / 'assets' / 'completion_audio' / f'{key}.wav'),
              'assets/completion_audio') for key in ('chiikawa', 'hachiware', 'usagi')]] + collect_data_files('tzdata'),
    hiddenimports=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtPdf', 'tkinter', 'pytest'],
    noarchive=False,
)
a.binaries = runtime.system_icu_filter(a.binaries, windows / 'System32')
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='DesktopBuddy',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    icon=str(root / 'assets' / 'icons' / 'buddy.ico'),
    version=str(root / 'tools' / 'windows_version.txt'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DesktopBuddy')
