from paddleocr import PaddleOCR
import numpy as np


ocr_session = PaddleOCR(lang="ch")


def ocr(img: np.ndarray) -> str:
    result = ocr_session.ocr(img, cls=False)
    return ''.join([line[-1][0] for line in result[0]])


if __name__ == "__main__":
    from PIL import Image
    img = np.array(Image.open("Screenshot 2024-01-05 013132.png"))
    print(ocr(img))
