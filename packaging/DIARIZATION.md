# Local speaker analysis

Lecture Studio can group recurring speakers within one recording. The analysis is CPU-based and runs in a separate process after recording or on request. Lecture audio stays on the computer. The model files are a separate installation.

## Sherpa ONNX on Windows

Source installations can add the optional runtime with the same Python environment used to run Studio.

```powershell
python -m pip install -r packaging/requirements-diarization.txt
```

With the Sherpa runtime available, open **More → Audio & local models → Local models** and choose
**Download 46.6 MB** under **Speaker identification**. Studio verifies both files before enabling
the downloaded pair. To use files already on your computer, place these two files in one folder
and choose **Use a model folder**.

| File to place in the folder | Source |
| --- | --- |
| `segmentation.onnx` | Extract `model.int8.onnx` from the [official sherpa model archive](https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2) and use that filename. |
| `embedding.onnx` | Download [ERes2Net from the sherpa release](https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx) and use that filename. |

Select this folder in Studio or place the files in `%LOCALAPPDATA%\Annie\LectureStudio\models\diarization`. For a source or test profile, the default is `models/diarization` under `ANNIE_DATA_DIR`. `ANNIE_DIARIZATION_MODEL_DIR` can point to a different directory.

After processing, the transcript filter lists each speaker, unassigned passages, and passages
that intersect overlapping model intervals. Assigning a speaker resolves an unassigned passage.
The overlapping speech filter continues to mark simultaneous speech so it can be replayed.

The SHA-256 values for the versions used in testing are below. The segmentation archive includes the upstream MIT license. The embedding originates from 3D-Speaker and should be distributed with its applicable notices. The Studio model setup uses separate downloads. [Sherpa documentation](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html) · [3D-Speaker](https://github.com/modelscope/3D-Speaker)

| Model | SHA-256 |
| --- | --- |
| Segmentation INT8 | `D582F4B4C6B48205DE7E0643C57DF0DF5615A3C176189BE3FC461E9D18827B5D` |
| ERes2Net embedding | `F1EE61BE04000B50392A63442E5DD9FEAEA7E81DDDD494D3647CF1C3D88A1498` |

## Community-1 source environment

Community-1 is an alternate offline backend for a source environment with `pyannote.audio` 4, PyTorch and their compatible audio dependencies. Download the official repository using your own approved Hugging Face access and follow the model card's offline setup. Select the complete local model folder containing `config.yaml`, `segmentation`, `embedding` and `plda`. The worker passes no token and sets Hugging Face offline mode. Community-1 uses CC BY 4.0. Its weights returned HTTP 401 without an account during this verification, so local inference was verified with sherpa. [Community-1 setup and license](https://huggingface.co/pyannote/speaker-diarization-community-1#offline-use)

## Windows CPU results

Measured with Python 3.14.3, sherpa-onnx 2.0.2 and AMD Ryzen 5 5600H, including model and subprocess startup. On a 36.703 s synthetic A → B → A clip with an 18 s pause and a changed speaking rate for the second A, both automatic and explicit two-speaker modes reused A's original label. Approximate DER was 5.29% against the synthesized phrase envelopes with no timing tolerance. Automatic mode took 5.982 s at an approximately 264 MiB sampled worker peak. Explicit two-speaker mode took 6.176 s at approximately 265 MiB.

On the 56.86 s public four-speaker recording, explicit four-speaker mode ran in 10.31 s and produced ten turns in four groups. Automatic mode ran in 9.593 s and produced seven groups. If extra groups appear, enter a known speaker count or merge the affected groups. The public sample smoke check has no time-aligned reference in this run. Classroom overlap, far-field noise and recognition accuracy require separate measurements. [Official public sample and example](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html)

A 131 s synthetic clip added white noise, two simultaneous turns, a 95 s gap and a pitch change for the returning A. The two-speaker run took 11.335 s. It returned both overlapping intervals and gave the first and returning A the same label.
