"""Compile the small audio helper with the installed Apple SDK, never at recording time."""
import argparse
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build_helper(root=ROOT):
    if sys.platform != 'darwin':
        raise RuntimeError('The ScreenCaptureKit helper requires the macOS SDK and must be built on a Mac.')
    target = root / 'native/macos/bin/LectureAudioCapture'
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['/usr/bin/xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5', '-O',
                    '-target', platform.machine() + '-apple-macosx14.0',
                    '-framework', 'ScreenCaptureKit', '-framework', 'CoreMedia',
                    '-framework', 'CoreAudio', '-framework', 'CoreGraphics',
                    str(root / 'native/macos/LectureAudioCapture.swift'), '-o', str(target)],
                   check=True, timeout=180)
    subprocess.run([str(target), '--self-test'], check=True, timeout=15)
    return target


if __name__ == '__main__':
    print(build_helper())
