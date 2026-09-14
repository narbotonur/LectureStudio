"""
NU Academic Portals Launcher Utility
Launches Moodle, Registrar, My.NU, and LibCal in Google Chrome
using the user's own browser account.
Uses complete process detachment so Chrome never interferes with Annie or the Qt event loop.
"""
import os
import sys
import subprocess
import webbrowser

CHROME_PROFILE = ""

MOODLE_URL = "https://moodle.nu.edu.kz/my/courses.php"
REGISTRAR_URL = "https://registrar.nu.edu.kz/"
MY_NU_URL = "https://my.nu.edu.kz/"
LIBCAL_URL = "https://nu-kz.libcal.com/spaces?lid=3244"

CANDIDATE_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
]


def get_chrome_executable() -> str:
    for path in CANDIDATE_CHROME_PATHS:
        if os.path.isfile(path):
            return path
    return "chrome"


def open_in_nu_chrome(url: str):
    """
    Opens a portal in the user's browser or an explicitly selected Chrome profile.
    Detaches completely from parent process so Annie never hangs or closes.
    """
    if not CHROME_PROFILE:
        return webbrowser.open(url)
    chrome_exe = get_chrome_executable()
    try:
        creationflags = 0
        if sys.platform == "win32":
            # DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP ensures child lives in separate group
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

        subprocess.Popen(
            [chrome_exe, f"--profile-directory={CHROME_PROFILE}", url],
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True
        )
        print(f"  [NU LINKS] Launched detached Chrome ({CHROME_PROFILE}) -> {url}")
    except Exception as e:
        print(f"  [NU LINKS] Fallback standard browser for {url}: {e}")
        try:
            webbrowser.open(url)
        except Exception:
            pass


def open_moodle():
    open_in_nu_chrome(MOODLE_URL)


def open_registrar():
    open_in_nu_chrome(REGISTRAR_URL)


def open_my_nu():
    open_in_nu_chrome(MY_NU_URL)


def open_libcal():
    open_in_nu_chrome(LIBCAL_URL)
