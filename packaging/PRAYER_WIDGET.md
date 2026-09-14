# Prayer times desktop widget

Open **More → Prayer times widget · Намаз**, or run:

```
python lecture_studio_entry.py --prayer-widget
```

This is a separate lightweight process. Studio, Whisper, camera and microphone
are not started. The translucent blue glass-style card uses scalable, natively
drawn prayer icons. It has no taskbar button; a tray/menu-bar icon provides Show,
Settings, Pin, Refresh and Quit. Drag the unpinned card to move it. The diagonal
arrow button switches compact/wide layouts and remembers the choice.

On **Windows**, click the **pushpin** to attach the card to Explorer's desktop
container, below ordinary application windows. Pinning also locks dragging and
disables always-on-top. Click it again (or use the tray menu) to unpin and move.
Pinning is remembered across login. This uses an existing Explorer desktop host;
it does not patch Explorer, create a wallpaper host or require administrator access.
Windows uses a non-layered painted surface and a rounded native region, attached
to the outer desktop host. Per-pixel alpha is disabled there: isolated tests of
layered children were not reliable in the real widget. DesktopPin explicitly
rejects layered HWNDs before attaching them. Corners may show pixel steps; fully
antialiased desktop corners remain unresolved. macOS retains per-pixel alpha.
If the desktop is unavailable or DPI modes differ, the card reports that it is not
pinned and remains floating. Restart the widget for a DPI mismatch. Explorer desktop
hosting is shell-dependent; the app retries a lost host without restarting Explorer.
Native attach/detach has been verified locally on Windows; all Windows shell versions
and Explorer-restart paths have not been exercised.

This is a desktop application widget, **not a Win+W Widgets-board provider** and
not an Apple WidgetKit extension. macOS retains floating-widget mode.

## Location and timing

Enter a city and country manually. No GPS or IP-location lookup is performed.
City/country and calculation parameters are sent to **https://api.aladhan.com**.
No Google account or API key is required. Settings and cached times are stored
locally in `prayer-widget.json` and `prayer-times-cache.json`, outside releases.

Choose the madhhab and calculation method separately. AlAdhan `school=1` supplies
the two-shadow Hanafi Asr convention; `school=0` supplies the one-shadow convention
used for Shafi'i, Maliki and Hanbali. Both exclude the object's noon shadow.
The widget does not invent four different timetables. Fajr/Isha conventions are
selected by the independent method setting. The default calculation is Karachi
(18°/18°), **not an official DUMK/Kazakhstan timetable**. Compare it with a trusted
local mosque schedule; per-prayer minute adjustments are available, but a fixed
offset cannot reproduce every seasonal difference. High-latitude calculation
uses the angle-based portion of night. Hijri dates are calculated, not local
moon-sighting declarations.

The source is queried at widget startup and once per city-local day while running.
Each refresh requests today and tomorrow so the post-Isha countdown uses the
actual following day's Fajr. Refresh is also available manually. Changes to the
city, Asr school, method or offsets invalidate previous cached settings.
Times include timezone offsets; the countdown does not assume the computer's
timezone is the selected city's timezone. Offline failures retain usable cached
days, visibly flag the failure and retry no more than once per ten minutes.
Old schedules are never relabelled as today's or used for a false countdown.

## Login startup

Settings includes an independent login-startup checkbox. It does not enable the
lecture watcher. On Windows the registration is HKCU Run `AnniePrayerWidget`.
On macOS it is `~/Library/LaunchAgents/local.annie.prayer-widget.plist`, taking
effect on the next login. Disable the same checkbox to remove this installation's
registration. Quit stops only the current widget process, not future login startup.

References:
- https://aladhan.com/prayer-times-api
- https://api.aladhan.com/v1/methods

Windows UI and offline regression checks are performed locally. Native macOS
window/menu-bar and login behaviour still needs testing on a Mac.
