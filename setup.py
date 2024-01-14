from cx_Freeze import setup, Executable

import sys

sys.setrecursionlimit(sys.getrecursionlimit() * 50)
import os

# Path to the paddleocr package in your environment
paddleocr_path = os.path.join(
    os.environ["VIRTUAL_ENV"], "Lib", "site-packages", "paddleocr"
)

# Define the build options
build_exe_options = {
    "packages": [
        "paddle",
        "paddleocr",
        "skimage",
        "pyclipper",
        "imghdr",
        "imgaug",
    ],  # Additional packages can be added as needed
    "includes": [
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        # "paddleocr.ppocr.utils.logging",
        # "paddleocr.ppocr.postprocess",
        # "paddleocr.ppocr.utils.utility",
        # "paddleocr.ppocr.utils.poly_nms",
        # "paddleocr.ppocr.utils.e2e_utils.pgnet_pp_utils",
        # "paddleocr.ppocr.data",
        # "paddleocr.ppocr.data.imaug",
        # "paddleocr.ppocr.data.imaug.vqa.augment",
        # "paddleocr.ppocr.data.simple_dataset",
    ],
    "include_files": [
        (paddleocr_path, 'lib/paddleocr')
        # (os.path.join(paddleocr_path, "tools"), "lib/paddleocr/tools"),
        # (
        #     os.path.join(paddleocr_path, "ppocr", "utils", "e2e_utils"),
        #     "lib/paddleocr/ppocr/utils/e2e_utils",
        # ),
    ],  # Use this to include additional files or directories if necessary
}

# Define the base and executables
base = None

executables = [Executable("main.py", base=base)]

# Call the setup function
setup(
    name="YourAppName",
    version="0.1",
    description="Your application description",
    options={"build_exe": build_exe_options},
    executables=executables,
)
