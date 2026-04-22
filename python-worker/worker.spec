# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for RedactSafe Python Worker.

Builds a standalone executable that bundles the Python worker
and its core dependencies (excluding heavy OCR engines).

Usage:
    pyinstaller worker.spec --onefile --name redact-worker

Note: PaddleOCR/PaddlePaddle require separate handling due to their
large size and native dependencies. For a full build with OCR support,
install PaddleOCR first and add --hidden-imports for paddle modules.
"""
import os
import sys

block_cipher = None
a = Analysis(
    ['worker.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('detection_rules.yaml', '.'),
    ],
    hiddenimports=[
        'fitz',  # PyMuPDF
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'yaml',
        'json',
        'hashlib',
        'base64',
        'io',
        'os',
        'tempfile',
        'traceback',
        'uuid',
        're',
        'coord_utils',
        'ocr_pipeline',
        'pii_detector',
        'name_detector',
        'pdf_sanitizer',
        'bbox_normalizer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'paddle',
        'paddleocr',
        'paddlenlp',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='redact-worker',
    debug=False,
    strip=True,
    upx=True,
    console=True,
)
