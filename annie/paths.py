"""Read-only application resources and per-user writable data are distinct."""
import os
from pathlib import Path
import sys
from annie.platform_support import user_data_dir

APP_DIR = Path(__file__).resolve().parent.parent
IS_PACKAGED = bool(getattr(sys, 'frozen', False))
PRIVATE_PROFILE = (IS_PACKAGED or sys.platform == 'darwin'
                   or (APP_DIR / 'lecture-studio.standalone').is_file()
                   or bool(os.environ.get('ANNIE_DATA_DIR')))
if os.environ.get('ANNIE_DATA_DIR'):
    DATA_DIR = Path(os.environ['ANNIE_DATA_DIR']).resolve()
elif PRIVATE_PROFILE:
    DATA_DIR = user_data_dir()
else:
    # Preserve the developer's existing library. Never import it into a release.
    DATA_DIR = APP_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
