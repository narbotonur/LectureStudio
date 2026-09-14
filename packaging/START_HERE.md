# Lecture Studio for Windows

1. Extract the entire ZIP into a folder you will keep, for example Documents\LectureStudio.
2. Open LectureStudio.exe (not LectureStudioWorker.exe). No Python installation or administrator rights are needed.
3. Complete Accounts & Setup. You can skip cloud services and use local recording and study timers.
4. Optional: right-click Create shortcuts.ps1 and choose Run with PowerShell to create Start-menu and desktop shortcuts. If script execution is blocked, create a shortcut to LectureStudio.exe manually; do not weaken Windows security settings.

Keep the _internal folder and worker executable beside LectureStudio.exe. Do not run from inside the ZIP.

## Your AI account

Get your own Gemini API key at https://aistudio.google.com/apikey and enter it in setup.
Choose a Gemini model available to your account. Cloud AI sends the lecture text/images/materials you ask it to process to Google; your account's quotas and any charges apply.
Local Whisper transcription runs on your PC. Its first use downloads the selected model from Hugging Face; allow time and disk space. CPU mode works without NVIDIA/CUDA. No microphone recording starts during setup or model download alone.

## Your Google Calendar

Prayer times are independent of Google Calendar: open **More > Prayer times widget · Намаз**.
See `PRAYER_WIDGET.md` for city selection, madhhab, calculation methods and separate login startup.

No Google login, password, OAuth client, or API key is included in this release.
1. Create your own Google Cloud project and enable Google Calendar API.
2. Configure Google Auth Platform branding/audience and Calendar scopes. For an External app in Testing, add your own Google email to Test users.
3. Create an OAuth client of type Desktop app; download its JSON file.
4. In Studio: More > Accounts & Setup > Import Google client JSON > Connect Google.
5. Sign into your own account in the browser and approve Calendar access.

Official instructions: https://developers.google.com/workspace/calendar/api/quickstart/python
Google OAuth apps in Testing can require reconnection after seven days. University administrators may restrict third-party access. The app cannot bypass that restriction.
Study sessions sync to the connected account's primary calendar. Pause time is excluded from totals; the calendar block spans the session's start/end.
Disconnect clears this laptop's saved login, not events already in Google. Revoke server-side access at https://myaccount.google.com/connections if desired. Pending unsynced sessions follow the next account you connect.

## Privacy, startup and updates

Personal files are stored in %LOCALAPPDATA%\Annie\LectureStudio, not in the extracted app folder.
API keys and Google tokens are protected with Windows DPAPI for your Windows login. This is not protection against malware running as you. Recordings, settings and study history are ordinary local files, not encrypted by Studio. Use Windows disk encryption if needed.
Portal buttons open your default browser; sign into Moodle/Registrar/MyNU/LibCal there using your own account.
Enable or disable silent startup in Accounts & Setup. Meeting detection suggests recording; it does not automatically capture every meeting. Obtain the necessary recording consent.
Before replacing the app folder, finish recordings and exit Studio and the watcher. Keep your personal data folder. To stop using the app, disable its startup setting, exit it, then remove the extracted application folder and shortcuts. Remove the personal data folder separately only if you want to erase your recordings/history.

## Release status

This is an unsigned Windows x64 application. Windows may show an unknown-publisher warning. Verify the source and published SHA-256 checksum; do not disable antivirus or SmartScreen. A verified publisher signature is a separate release step requiring the publisher's certificate.
Included dependency licenses are retained in _internal. Third-party portal icons belong to their respective owners; this app is not an official university product.
