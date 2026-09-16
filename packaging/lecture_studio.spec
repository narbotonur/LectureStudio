from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, collect_data_files, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / 'annie/gui/assets/portals'), 'annie/gui/assets/portals')]
datas += [(str(root / 'annie/update_install.ps1'), 'annie')]
datas += collect_data_files('tzdata')
binaries = []
hidden = ['soundcard', 'win32crypt', 'win32timezone', 'pycaw.pycaw', 'comtypes.client',
          'google.auth.transport.requests', 'google_auth_oauthlib.flow', 'googleapiclient.discovery',
          'google.genai', 'pypdf', 'PIL.Image', 'PyQt5.QtSvg']
for package in ('faster_whisper', 'av', 'tokenizers', 'soundcard'):
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hidden += imports
for package in ('ctranslate2', 'onnxruntime'):
    binaries += collect_dynamic_libs(package)
hidden += ['onnxruntime.capi._pybind_state']
for package in ('google-genai', 'google-api-python-client', 'google-auth', 'faster-whisper', 'huggingface-hub'):
    datas += copy_metadata(package)

a = Analysis([str(root / 'lecture_studio_entry.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['torch', 'tensorflow', 'jax', 'matplotlib', 'pandas', 'scipy',
                       'transformers', 'sympy', 'sklearn', 'onnx', 'onnxruntime.tools',
                       'onnxruntime.quantization', 'onnxruntime.transformers',
                       'IPython', 'notebook', 'PySide6', 'PyQt6', 'tkinter',
                       'annie.main', 'annie.gui.app', 'annie.skills', 'annie.vision',
                       'annie.brain', 'annie.live', 'annie.web_agent'],
             noarchive=False, optimize=1)
# Qt ships an older MSVC runtime beside its DLLs. Its runtime hook can load
# that copy first, breaking newer ONNX builds. Use one matched runtime in all
# locations, and rely on Windows 10/11's own UCRT/API-set system components.
system32 = Path(os.environ['SystemRoot']) / 'System32'
crt_names = {'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
             'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll'}
normalized = []
for destination, source, kind in a.binaries:
    name = Path(destination).name.lower()
    if name == 'ucrtbase.dll' or name.startswith('api-ms-win-'):
        continue
    if name in crt_names and (system32 / name).is_file():
        source = str(system32 / name)
    normalized.append((destination, source, kind))
for name in crt_names:
    if (system32 / name).is_file() and not any(item[0].lower() == name for item in normalized):
        normalized.append((name, str(system32 / name), 'BINARY'))
a.binaries = normalized
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LectureStudio',
          console=False, debug=False, strip=False, upx=False)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LectureStudioWorker',
             console=True, debug=False, strip=False, upx=False)
coll = COLLECT(gui, worker, a.binaries, a.datas, strip=False, upx=False, name='LectureStudio')
