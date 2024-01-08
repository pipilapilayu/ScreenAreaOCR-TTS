from flask import Flask, request, jsonify
import pickle
import numpy as np


app = Flask(__name__)


from paddleocr import PaddleOCR
ocr_session = PaddleOCR(lang="ch", det=False)


def paddle_ocr_infer_fn(img: np.ndarray) -> str:

    result = ocr_session.ocr(img, cls=False)
    try:
        return ''.join([line[-1][0] for line in result[0]])
    except Exception as e:
        print(e)
        return ""


# def easy_ocr_infer_fn(img: np.ndarray) -> str:
#     import easyocr
#     ocr_session = easyocr.Reader(['ch_sim', 'en'])
#     result = ocr_session.readtext(img)
#     try:
#         return ''.join([line[-2] for line in result])
#     except Exception as e:
#         print(e)
#         return ""


@app.route("/ocr", methods=["POST"])
def ocr():
    if "file" not in request.files:
        return jsonify({"result": "no file"}), 400
    file = request.files["file"]
    img: np.ndarray = pickle.loads(file.read())
    return jsonify({"result": paddle_ocr_infer_fn(img)})



if __name__ == "__main__":
    app.run(port=48080)