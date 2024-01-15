from mss.windows import MSS as mss
import numpy as np
from PIL import Image


def pil_frombytes(im):
    """Efficient Pillow version."""
    return np.array(Image.frombytes("RGB", im.size, im.bgra, "raw", "BGRX"))


def take_region_screenshot(left: int, top: int, right: int, lower: int) -> np.ndarray:
    with mss() as sct:
        return pil_frombytes(sct.grab((left, top, right, lower)))


if __name__ == "__main__":
    img = take_region_screenshot(0, 0, 1920, 1080)
    from PIL import Image

    Image.fromarray(img).show()
