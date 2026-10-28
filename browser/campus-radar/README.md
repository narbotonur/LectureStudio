# Campus Radar: NU WeBWorK adapter

Local development extension, not yet a published Chrome Web Store package. Installation is a separate, explicit user action. Do not install it silently or bypass school-managed browser policies.

1. In Lecture Studio open **More → Campus Radar → Enable browser receiver** and copy the pairing code.
2. After approving installation, load this folder as an unpacked extension using Chrome's extension management page. Reload existing WeBWorK tabs once after installation.
3. Open a signed-in NU WeBWorK course page, open the extension popup, paste the code, and choose **Watch this course**.
4. Leave Lecture Studio and a signed-in tab for each watched course running. Review source freshness in Campus Radar. Use **Stop all watching** or disable the receiver to stop.

Permissions: `storage`, `alarms`, the NU WeBWorK host, and HTTP loopback. Chrome host permission patterns cannot be restricted to a port; code fixes the destination to `127.0.0.1:8768`. No Gmail, cookies, scripting, downloads, broad tabs or Chrome notification permissions. The pairing code stays in extension-local trusted storage; the desktop copy uses Windows DPAPI / macOS Keychain. It permits local Radar writes, not reading stored coursework. No cloud AI requests.

Scope: the English NU WeBWorK course index, regular assignment cards only. It requests a course index using the existing tab session and sends assignment titles, canonical links, quoted due text, explicit offset dates and open/closed/unknown status. It does not read grades, answers, cookies, password fields or student identifiers. User/session query parameters are removed. Login, unknown pages and empty extraction are failures; unsupported date/card formats are partial, never a clean success. Closed is availability, not completion.

Polling is approximately every five minutes while Chrome runs; no checks during shutdown/sleep, no promise of continuous coverage. Notifications request Windows tray messages while Lecture Studio's receiver runs; OS settings can suppress display. Delivery attempts are deduplicated independently from review state. The initial baseline gets one summary per course, not one alert per old assignment. This version detects new observations and changed fields; it does not yet schedule advance deadline reminders.

Offline tests: `node --test browser/campus-radar/tests/*.test.cjs`. Receiver tests use synthetic data and a private temporary profile: `python -B -m unittest discover -s tests -p test_campus*.py`.
