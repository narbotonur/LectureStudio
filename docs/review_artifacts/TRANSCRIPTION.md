# Transcription validation

The benchmark JSON records one actual `small` inference run on a newly generated,
fictional English lecture. It contains no user recordings. Generate the WAV in a
temporary directory on Windows with PowerShell:

```powershell
$taskDirectory = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ('studio-speech-' + [guid]::NewGuid()))
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$sample = Join-Path $taskDirectory.FullName 'lecture-fixture.wav'
$speaker.SetOutputToWaveFile($sample, $format)
$speaker.Speak('This is a fictional lecture for testing. Your computer systems assignment is due on Friday at five P M. For the exam, review the stack pointer, saved registers, and recursive procedure calls. Practice the examples from lecture before next Wednesday.')
$speaker.Dispose()
python -B tools/benchmark_transcription.py --audio $sample --model small --language en
```

The benchmark always uses an isolated temporary profile. Without `--audio`, it
runs a deterministic fake-model fixture that checks the capture/spool/event path
only. Real-file mode can load/download the requested Whisper model. Add
`--backend meta_voice` only when you intend to send that file to Meta using an
API key supplied through `META_API_KEY` or `MODEL_API_KEY`.

On the tested Windows environment CUDA reported one GPU, but the three required
CUDA/cuDNN DLLs were absent from the loader path; the application used CPU. This
does not establish why every historical lecture was slow. The new language hint,
real-time factor, first-text latency, backend/device and backlog measurements
make subsequent diagnosis observable. No CUDA libraries were installed.

## Provider contract

The implementation follows Meta's [speech guide](https://dev.meta.ai/docs/speech-to-text),
[realtime reference](https://dev.meta.ai/docs/api-reference/voice/realtime), and
[file reference](https://dev.meta.ai/docs/api-reference/voice/transcribe).

Realtime uses handshake authentication, raw PCM16, cumulative partial updates,
finalized speech turns and an explicit end-of-input frame. Connections rotate
before the documented 60-minute cap. If cloud transport fails, capture continues
to disk while Local Whisper resumes after the last finalized turn. File uploads
use supported PCM WAV chunks below the request duration/size caps.

Russian and Kazakh are absent from Meta's documented evaluated language list;
selecting either uses Local Whisper. Cloud is optional and requires account
access and an API key. No authenticated Muse Voice call, real microphone run or
hour-long cloud rotation test was performed in this validation.

Final transcript events carry a separate structured segment with seconds into
the saved audio. Partial text is replaceable UI state and never enters evidence.
The adapter buffers out-of-order turn finalization before committing audio order.
