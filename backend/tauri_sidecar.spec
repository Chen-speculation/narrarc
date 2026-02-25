# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for narrative_mirror Tauri sidecar.
# Build: pyinstaller tauri_sidecar.spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ChromaDB and LangGraph need explicit collection
hiddenimports = [
    'chromadb',
    'chromadb.api',
    'chromadb.db.impl',
    'chromadb.db.impl.sqlite',
    'chromadb.segment.impl.manager',
    'chromadb.segment.impl.metadata',
    'chromadb.segment.impl.vector',
    'langgraph',
    'langgraph.graph',
    'langgraph.graph.state',
    'langgraph.checkpoint',
    'langchain_core',
    'langchain_openai',
]
hiddenimports += collect_submodules('chromadb')
hiddenimports += collect_submodules('langgraph')

datas = list(collect_data_files('chromadb'))

a = Analysis(
    ['tauri_sidecar.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='backend',  # Platform suffix added by build script
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Keep console for stderr/debug output
)
