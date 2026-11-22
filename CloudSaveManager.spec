# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller CloudSaveManager.spec  (или build.bat)
block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('assets', 'assets')],          # иконки, check.svg, chevron.svg, assets/fonts
    hiddenimports=['PyQt5.QtSvg', 'PyQt5.QtNetwork', 'yaml', 'cryptography.hazmat.primitives.kdf.scrypt', 'keyring.backends.Windows', 'keyring.backends.SecretService'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'pytest'],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='CloudSaveManager',
    debug=False,
    strip=False,
    upx=False,
    console=False,                          # без чёрного окна консоли
    icon='assets/icon.ico',
)
