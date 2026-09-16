"""Experimental native-architecture .app; build on macOS, not Windows."""
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, copy_metadata, collect_data_files

if sys.platform != 'darwin':
    raise RuntimeError('Build the macOS bundle on a Mac using its native Python architecture.')

root = Path(SPECPATH).parent
import runpy
studio_version = runpy.run_path(str(root / 'annie/version.py'))['VERSION']
datas = [(str(root / 'annie/gui/assets/portals'), 'annie/gui/assets/portals')]
datas += collect_data_files('tzdata')
helper = root / 'native/macos/bin/LectureAudioCapture'
if not helper.is_file():
    raise RuntimeError('Compile the ScreenCaptureKit helper with tools/build_macos_audio.py first.')
binaries = [(str(helper), '.')]
hidden = ['soundcard', 'keyring.backends.macOS', 'AppKit', 'Quartz', 'AVFoundation',
          'google.auth.transport.requests', 'google_auth_oauthlib.flow',
          'googleapiclient.discovery', 'google.genai', 'pypdf', 'PIL.Image', 'PyQt5.QtSvg']
for package in ('faster_whisper', 'av', 'tokenizers', 'soundcard'):
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hidden += imports
for package in ('ctranslate2', 'onnxruntime'):
    binaries += collect_dynamic_libs(package)
hidden += ['onnxruntime.capi._pybind_state']
for package in ('google-genai', 'google-api-python-client', 'google-auth',
                'faster-whisper', 'huggingface-hub', 'keyring'):
    datas += copy_metadata(package)

a = Analysis([str(root / 'lecture_studio_entry.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['torch', 'tensorflow', 'jax', 'matplotlib', 'pandas', 'scipy',
                       'transformers', 'sympy', 'sklearn', 'onnx', 'onnxruntime.tools',
                       'onnxruntime.quantization', 'onnxruntime.transformers',
                       'IPython', 'notebook', 'PySide6', 'PyQt6', 'tkinter',
                       'win32crypt', 'win32gui', 'win32process', 'pycaw', 'comtypes',
                       'annie.main', 'annie.gui.app', 'annie.skills', 'annie.vision',
                       'annie.brain', 'annie.live', 'annie.web_agent'],
             noarchive=False, optimize=1)
pyz = PYZ(a.pure)
# Put the native helper in Contents/MacOS, beside the GUI and Python worker.
a.binaries = [(destination, source, 'EXECUTABLE' if destination == 'LectureAudioCapture' else kind)
              for destination, source, kind in a.binaries]
signing = {'codesign_identity': os.environ.get('ANNIE_CODESIGN_IDENTITY') or None,
           'entitlements_file': str(root / 'packaging/macos-entitlements.plist')}
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LectureStudio',
          console=False, debug=False, strip=False, upx=False, argv_emulation=False, **signing)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LectureStudioWorker',
             console=True, debug=False, strip=False, upx=False, **signing)
coll = COLLECT(gui, worker, a.binaries, a.datas, strip=False, upx=False, name='LectureStudio')
# COLLECT inherits console=True from the worker. Passing gui last explicitly
# gives BUNDLE the GUI's activation policy while keeping both executables.
app = BUNDLE(coll, gui, name='Lecture Studio.app', bundle_identifier='local.annie.lecture-studio',
             version=studio_version, info_plist={
                 'CFBundleDisplayName': 'Lecture Studio',
                 'LSMinimumSystemVersion': '14.0',
                 # Start quietly. Normal Studio windows opt into a Dock icon
                 # at runtime; login watchers never briefly flash one.
                 'LSUIElement': True,
                 'NSHighResolutionCapable': True,
                 'NSMicrophoneUsageDescription': 'Record lectures you explicitly start and transcribe them into study notes.',
                 'NSLocalNetworkUsageDescription': 'Receive audio from the phone microphone address you configure.',
                 'NSAudioCaptureUsageDescription': 'Record meeting sound only when you start a system-audio recording.',
             })
