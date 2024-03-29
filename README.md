
# ScreenAreaOCR-TTS

An OCR-TTS GUI application written in Qt6. Aims to provide user-friendly interface for reading selected screen area using custom TTS & OCR engine.

![demo](demo.gif)

## Usage

You need a TTS server to run this. Please refer to the implementation of [TTS server](https://github.com/pipilapilayu/Bert-VITS-onnx-restful-server) and [OCR server](https://github.com/pipilapilayu/ScreenAreaOCR-TTS/blob/master/ocr_server.py) for more API details.

In actual deployment, we used compiled Bert-VITS2 2.3 library with custom server implementation for GPU inference. Source code is collapsed here for simplicity.

<details>

<summary>Custom server src</summary>

```python
from loguru import logger


logger.add("tts.log", rotation="1 week", backtrace=True, diagnose=True)    # Once the file is too old, it's rotated


with logger.catch():
    from sys import stderr
    from flask import Flask, jsonify, request, Response
    from tools.sentence import split_by_language
    import re_matching
    from io import BytesIO
    import soundfile
    from typing import Dict
    import json
    import numpy as np
    import subprocess
    import utils
    import os
    from config import config
    import torch
    import torchaudio
    from infer import infer_multilang, get_net_g
    import pyloudnorm

    app = Flask(__name__)

    mapping: Dict[str, str] = (
        json.load(open("mapping.json", "r", encoding="utf-8")) if os.path.exists("mapping.json") else {}
    )

    device = config.webui_config.device
    logger.info("using device: %r" % device)
    hps = utils.get_hparams_from_file(config.webui_config.config_path)
    net_g = get_net_g(
        model_path=config.webui_config.model, device=device, hps=hps
    )
    speaker_ids = hps.data.spk2id
    speakers = list(speaker_ids.keys())


def normalize_loudness(y: np.ndarray, fs: int, target_loudness=-23) -> np.ndarray:
    meter = pyloudnorm.Meter(fs)
    loudness = meter.integrated_loudness(y)
    normalized = pyloudnorm.normalize.loudness(y, loudness, target_loudness)
    return normalized


def generate_audio_multilang(
    slices,
    sdp_ratio,
    noise_scale,
    noise_scale_w,
    length_scale,
    speaker,
    language,
    skip_start=False,
    skip_end=False,
):
    audio_list = []
    for idx, piece in enumerate(slices):
        skip_start = idx != 0
        skip_end = idx != len(slices) - 1
        audio = infer_multilang(
            piece,
            sdp_ratio=sdp_ratio,
            noise_scale=noise_scale,
            noise_scale_w=noise_scale_w,
            length_scale=length_scale,
            sid=speaker,
            device=device,
            net_g=net_g,
            language=language[idx],
            skip_start=skip_start,
            skip_end=skip_end,
        ).squeeze()
        audio_list.append(audio)
    return audio_list


def process_auto(text):
    _text, _lang = [], []
    for slice in text.split("|"):
        if slice == "":
            continue
        temp_text, temp_lang = [], []
        try:
            sentences_list = split_by_language(slice, target_languages=["zh", "en", "ja"])
        except Exception as e:
            logger.error(e)
            logger.error("split_by_language failed, fallback to zh and en")
            sentences_list = split_by_language(slice, target_languages=["zh", "en"])

        for sentence, lang in sentences_list:
            if sentence == "":
                continue
            temp_text.append(sentence)
            if lang == "ja":
                lang = "jp"
            temp_lang.append(lang.upper())
        _text.append(temp_text)
        _lang.append(temp_lang)
    return _text, _lang


def process_text(
    text: str,
    speaker,
    sdp_ratio,
    noise_scale,
    noise_scale_w,
    length_scale,
):
    _text, _lang = process_auto(text)
    logger.info(f"Text: {_text}, Lang: {_lang}")
    return generate_audio_multilang(
        _text,
        sdp_ratio,
        noise_scale,
        noise_scale_w,
        length_scale,
        speaker,
        _lang,
    )


def format_utils(text, speaker):
    _text, _lang = process_auto(text)
    res = f"[{speaker}]"
    for lang_s, content_s in zip(_lang, _text):
        for lang, content in zip(lang_s, content_s):
            res += f"<{lang.lower()}>{content}"
        res += "|"
    return "mix", res[:-1]


def tts_fn(
    text: str,
    speaker=0,
    sdp_ratio=0.5,
    noise_scale=0.6,
    noise_scale_w=0.9,
    length_scale=1.0,
):
    audio_list = process_text(
        text,
        speaker,
        sdp_ratio,
        noise_scale,
        noise_scale_w,
        length_scale,
    )

    audio_concat = np.concatenate(audio_list)
    return normalize_loudness(audio_concat, 44100)


def tts_split(
    text: str,
    speaker=0,
    sdp_ratio=0.5,
    noise_scale=0.6,
    noise_scale_w=0.9,
    length_scale=1.0,
    cut_by_sent=False,
    interval_between_para=1,
    interval_between_sent=0.2,
):
    # while text.find("\n\n") != -1:
    #     text = text.replace("\n\n", "\n")
    text = text.replace("\n", " ")
    text = text.replace("|", "")
    para_list = re_matching.cut_para(text)
    para_list = [p for p in para_list if p != ""]
    audio_list = []
    for p in para_list:
        if not cut_by_sent:
            audio_list.extend(
                process_text(
                    p,
                    speaker,
                    sdp_ratio,
                    noise_scale,
                    noise_scale_w,
                    length_scale,
                )
            )
        else:
            audio_list_sent = []
            sent_list = re_matching.cut_sent(p)
            sent_list = [s for s in sent_list if s != ""]
            for s in sent_list:
                audio_list_sent += process_text(
                    s,
                    speaker,
                    sdp_ratio,
                    noise_scale,
                    noise_scale_w,
                    length_scale,
                )
            if (interval_between_para - interval_between_sent) > 0:
                silence = np.zeros(
                    (int)(44100 * (interval_between_para - interval_between_sent))
                )
                audio_list_sent.append(silence)
            audio_list.append(audio_list_sent)
    audio_concat = np.concatenate(audio_list)
    return normalize_loudness(audio_concat, 44100)


def encode_wav(audio: np.ndarray) -> bytes:
    f = BytesIO()
    soundfile.write(f, audio, 44100, format="WAV")
    return f.getvalue()


def encode_mp3(audio: np.ndarray) -> bytes:
    # https://superkogito.github.io/blog/2020/03/19/ffmpeg_pipe.html
    ffmpeg_command = [
        "ffmpeg",
        "-i",
        "-",
        "-f",
        "mp3",
        "-acodec",
        "libmp3lame",
        "-b:a",
        "320k",
        "-",
    ]
    process = subprocess.Popen(
        ffmpeg_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    mp3_data, err = process.communicate(input=encode_wav(audio))
    if process.returncode != 0:
        raise Exception(f"ffmpeg error: {err.decode()}")
    return mp3_data


@app.get("/tts")
def tts():
    logger.info("received tts request")
    try:
        text = request.args.get("text", type=str)
        if not text:
            return jsonify({"status": 400, "message": "No text provided"})
        length_scale = request.args.get("length_scale", 1.2, type=float)
        if not 0.1 <= length_scale <= 2:
            return jsonify(
                {
                    "status": 400,
                    "message": "length_scale must be between 0.1 and 2",
                }
            )
        for src, dst in mapping.items():
            text = text.replace(src, dst)

        audio = tts_split(
            text,
            length_scale=length_scale,
        )

        target_fs = request.args.get("fs", default=44100, type=int)
        format = request.args.get("format", default="mp3", type=str)

        if target_fs != 44100:
            audio = torchaudio.functional.resample(torch.from_numpy(audio), 44100, target_fs).numpy()

        match format:
            case "mp3":
                return Response(encode_mp3(audio), mimetype="audio/mpeg")
            case "wav":
                return Response(encode_wav(audio), mimetype="audio/wav")
            case _:
                return jsonify({"status": 400, "message": "Unrecognized format"})
    except Exception as e:
        logger.error(e)
        return jsonify({"status": 400, "message": str(e)})


if __name__ == "__main__":
    tts_split("你好，hello，こんにちは")
    app.run(host="localhost", port=47867)
```

Please notice that we have heavily modified the original Bert-VITS2 2.3 codebase. The actual function signature of `infer_multilang` and `get_net_g` might be different from the original ones.

</details>

### Change TTS server & API

We now support entering your custom TTS server (but it would not be saved so far). After open the application, click the `Settings` button on the top right corner, and click on the `Set TTS API URL` option.

### Start GUI

Fire up your TTS server first, or use online ones. Then right-click on `start.ps1` -> `Run with Powershell` to start the GUI.

<details>
  <summary>Why we need script</summary>

  cx_Freeze packs all .dlls into the `lib` folder. Technically, the user should not need to install any dependency. Yet we need to tell the program to search for dlls in it. Thus we provide a script to dynamically scan folders with .dlls in them, and fed it to the program.
</details>

If you are running from source code, run `python main.py` instead.

#### Make sure it's using GPU

CPU inference is slow, especially for OCR. You may check if they are using GPU by looking at the console output of GUI. However, please don't be confused by this output:

```powershell
> .\build\exe.win-amd64-3.10\main.exe
[2024/01/13 22:00:08] ppocr DEBUG: Namespace(help='==SUPPRESS==', use_gpu=True, ...
```

`use_gpu=True` would always be true. To actually check if the program is gonna work, you need to actually start an OCR request by pressing your hotkey.

## Compile into exe

### Prepare CUDA & CUDNN

Please refer to [cuda](https://developer.nvidia.com/cuda-downloads) and [cudnn](https://developer.nvidia.com/cudnn) official website for installation.

You may check if your CUDA is installed correctly by running `nvcc -V` in cmd.

### Prepare venv

```powershell
python -m venv .venv_win
.venv_win\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install paddlepaddle-gpu==2.6.0.post120 -f https://www.paddlepaddle.org.cn/whl/windows/mkl/avx/stable.html
pip install flask paddleocr pyqt6 loguru result sounddevice pynput mss pywin32 soundfile cx_Freeze maturin
```

### Fix paddlepaddle bug

Open `.venv_win\Lib\site-packages\paddle\base\core.py`, comment out line 409-415:

```python
    if hasattr(site, 'USER_SITE'):
        lib_dir = os.path.sep.join([site.USER_SITE, 'paddle', 'libs'])
        if os.path.exists(lib_dir):
            _set_paddle_lib_path(lib_dir)
            set_paddle_custom_device_lib_path(
                os.path.sep.join([lib_dir, '..', '..', 'paddle_custom_device'])
            )
```

You may also change it to `if hasattr(site, 'USER_SITE') and isinstance(site.USER_SITE, str):`, should also work tho not tested.

### Compile reqwest_wrapper

Make sure you have [rustup](https://win.rustup.rs/x86_64) on windows installed, including [dependencies](https://rust-lang.github.io/rustup/installation/windows-msvc.html#installing-only-the-required-components-optional). Then run the following commands:

```powershell
cd reqwest_wrapper
maturin build --release
maturin develop --release
cd ..
```

### Use cx_Freeze to compile

```powershell
python setup.py build_exe --build-exe=.\output_build
```

Each compile would write ~8G data to disk. You may want to set the destination on a mechanical hard drive to avoid worn out SSD.

## Todo

- [x] Make OCR async
- [x] Make TTS tasks async
- [x] Add GUI options to set APIs
- [x] Add config files to store API / capture window info
- [x] Add global logging
- [x] Make capture window separated from main window by default
- [ ] Add option to stay on top
- [x] Auto stick to the bottom
- [x] Maybe auto clean up the queue?
- [x] Make it compile into ~~single file~~ exe using ~~pyinstaller~~ cx_Freeze
