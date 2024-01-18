from cx_Freeze import setup, Executable
import os
import sys
import shutil

sys.setrecursionlimit(sys.getrecursionlimit() * 50)

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
    ],
    "include_files": [
        (paddleocr_path, "lib/paddleocr"),
        "start.ps1"
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
