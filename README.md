
# ScreenAreaOCR-TTS

An OCR-TTS GUI application written in Qt6. Aims to provide user-friendly interface for reading selected screen area using custom TTS & OCR engine.

![demo](demo.gif)

## Usage

You need both TTS and OCR server. Please refer to the implementation of [TTS server](https://github.com/pipilapilayu/Bert-VITS-onnx-restful-server) and [OCR server](https://github.com/pipilapilayu/ScreenAreaOCR-TTS/blob/master/ocr_server.py) for more API details.

After correctly setting TTS and OCR URL, you may start using the application. The provided TTS and OCR server has only been tested on pure CPU inference, in which case the latency would be very high, as shown in the demo above.

## Todo

- [x] Make OCR async
- [x] Make TTS tasks async
- [ ] Add GUI options to set APIs
- [ ] Add config files to store API / capture window info
- [ ] Make it compile into single file using pyinstaller

