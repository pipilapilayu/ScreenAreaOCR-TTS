from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QApplication,
    QMainWindow,
    QHBoxLayout,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QMenuBar,
    QDialog,
    QLineEdit,
    QDialogButtonBox,
    QPushButton,
    QMessageBox,
)
from PyQt6.QtGui import QPainter, QColor, QMouseEvent
from screenshot_utils import take_region_screenshot
from queue import Queue
import win32gui
import numpy as np
from typing import Optional, Callable, Any, Tuple, Literal
from result import Result, Ok, Err
from functools import partial
import sounddevice as sd
import soundfile as sf
from io import BytesIO
from threading import Lock
from pynput import mouse, keyboard
from loguru import logger
from ocr_server import paddle_ocr_infer_fn
import reqwest_wrapper


class CaptureWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.border_color = QColor(255, 0, 0)  # Red color
        self.border_width = 10  # Border width in pixels
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.grab_flags = [False] * 4  # Share grab status between mouse event callbacks

    def paintEvent(self, _event):
        painter = QPainter(self)
        pen = painter.pen()
        pen.setColor(self.border_color)  # Set the pen color for the border
        pen.setWidth(self.border_width)  # Set the pen width for the border
        painter.setPen(pen)

        # Draw top border
        painter.drawLine(0, 0, self.width(), 0)

        # Draw bottom border
        painter.drawLine(0, self.height(), self.width(), self.height())

        # Draw left border
        painter.drawLine(0, 0, 0, self.height())

        # Draw right border
        painter.drawLine(self.width(), 0, self.width(), self.height())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mousePressPos = event.globalPosition().toPoint()
            self.mouseMovePos = event.globalPosition().toPoint()

            rect = self.geometry()

            assert self.mousePressPos is not None
            # Determine which edge is being dragged
            left_edge = abs(self.mousePressPos.x() - rect.left()) < self.border_width
            right_edge = abs(self.mousePressPos.x() - rect.right()) < self.border_width
            top_edge = abs(self.mousePressPos.y() - rect.top()) < self.border_width
            bottom_edge = (
                abs(self.mousePressPos.y() - rect.bottom()) < self.border_width
            )
            for i, v in enumerate((left_edge, right_edge, top_edge, bottom_edge)):
                self.grab_flags[i] = v

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            currentPos = event.globalPosition().toPoint()
            assert self.mouseMovePos is not None
            dx = currentPos.x() - self.mouseMovePos.x()
            dy = currentPos.y() - self.mouseMovePos.y()
            rect = self.geometry()

            left_edge, right_edge, top_edge, bottom_edge = self.grab_flags

            # Resize window accordingly
            if left_edge:
                rect.setLeft(
                    min(rect.left() + dx, rect.right() - (self.border_width << 1))
                )
            if right_edge:
                rect.setRight(
                    max(rect.right() + dx, rect.left() + (self.border_width << 1))
                )
            if top_edge:
                rect.setTop(
                    min(rect.top() + dy, rect.bottom() - (self.border_width << 1))
                )
            if bottom_edge:
                rect.setBottom(
                    max(rect.bottom() + dy, rect.top() + (self.border_width << 1))
                )

            self.setGeometry(rect)

            self.mouseMovePos = currentPos

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mousePressPos = None
            self.mouseMovePos = None
            for i, _ in enumerate(self.grab_flags):
                self.grab_flags[i] = False


class LightWidget(QWidget):
    def __init__(self, parent=None, on_color=QColor("green"), off_color=QColor("red")):
        super().__init__(parent)
        self.setFixedSize(20, 20)  # Set the size of the light indicator
        self.light_on = False
        self.on_color = on_color
        self.off_color = off_color

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw a filled circle with the on or off color
        painter.setBrush(self.on_color if self.light_on else self.off_color)
        painter.drawEllipse(0, 0, self.width(), self.height())

    def turn_on(self):
        self.light_on = True
        self.update()  # Trigger a repaint

    def turn_off(self):
        self.light_on = False
        self.update()  # Trigger a repaint


class TaskWorker(QThread):
    task_finished = pyqtSignal(object)

    def __init__(
        self,
        task_queue: Queue,
        task_handler: Callable[..., Any],
        light_indicator: Optional[LightWidget] = None,
    ) -> None:
        super().__init__()
        self.task_queue = task_queue
        self.task_handler = task_handler
        self.running = True
        self.light_indicator = light_indicator

    def run(self) -> None:
        while self.running:
            if self.task_queue.empty():
                self.msleep(50)
            else:
                if self.light_indicator is not None:
                    self.light_indicator.turn_on()
                task = self.task_queue.get()
                result = self.task_handler(task)
                self.task_queue.task_done()
                if self.light_indicator is not None:
                    self.light_indicator.turn_off()
                self.task_finished.emit(result)

    def stop(self):
        self.running = False


class TTSHelper:
    """Help TaskWorker to process TTS tasks, while providing a way to change TTS settings during runtime
    Basically a function with it's parameters partially applied & could be modified
    """

    def __init__(self, tts_client: reqwest_wrapper.TTSClient, tts_api: str) -> None:
        self.tts_client = tts_client
        self.tts_api = tts_api

    def __call__(
        self, task: Tuple[str, QListWidgetItem]
    ) -> Tuple[Result[bytes, str], QListWidgetItem]:
        text, item = task
        print("Processing TTS request:", text)

        def inner(req_url: str) -> Result[bytes, str]:
            try:
                audio_data = self.tts_client.get_tts(req_url)
                return Ok(audio_data)
            except Exception as e:
                return Err(str(e))

        res = inner(self.tts_api % text)
        return res, item


class TTSAPIInputDialog(QDialog):
    def __init__(self, parent: QWidget | None, tts_helper: TTSHelper) -> None:
        super().__init__(parent)
        self.tts_helper = tts_helper

        self.setWindowTitle("Set TTS API URL")
        self.layout = QVBoxLayout(self)

        urlLine = QHBoxLayout()
        self.urlText = QLineEdit(self.tts_helper.tts_api, self)

        self.testButton = QPushButton("Test", self)
        self.testButton.clicked.connect(self.testAPI)

        urlLine.addWidget(self.urlText)
        urlLine.addWidget(self.testButton)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.layout.addLayout(urlLine)
        self.layout.addWidget(self.buttons)

    def testAPI(self):
        url = self.urlText.text()
        try:
            self.testButton.setEnabled(False)
            audio_data = self.tts_helper.tts_client.get_tts(url % "测试")
            data, fs = sf.read(BytesIO(audio_data))
            sd.play(data, fs)
            sd.wait()
            self.testButton.setEnabled(True)
        except Exception as e:
            messageBox = QMessageBox(self)
            messageBox.setText(str(e))
            messageBox.exec()
            self.testButton.setEnabled(True)

    @classmethod
    def getNewURL(cls, parent: QWidget | None, tts_helper: TTSHelper) -> str:
        dialog = cls(parent, tts_helper)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            return dialog.urlText.text()
        else:
            return tts_helper.tts_api


HotkeyType = Tuple[Literal["keyboard", "mouse", "null"], str]


class HotKeyInputDialog(QDialog):
    def __init__(self, parent: QWidget | None, cur_key: HotkeyType) -> None:
        super().__init__(parent)
        self.key = cur_key

        self.rec_kb_listener = None
        self.rec_ms_listener = None

        self.setWindowTitle("Set Hotkey")
        self.layout = QVBoxLayout(self)

        self.labelLayout = QHBoxLayout()
        self.labelLayout.addWidget(QLabel("Current hotkey: ", self))
        self.keyTypeLabel = QLabel(self.key[0], self)
        self.keyNameLabel = QLabel(self.key[1], self)
        self.labelLayout.addWidget(self.keyTypeLabel)
        self.labelLayout.addWidget(self.keyNameLabel)

        self.rec_button = QPushButton("Record", self)
        self.rec_button.clicked.connect(self.record)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.layout.addLayout(self.labelLayout)
        self.layout.addWidget(self.rec_button)
        self.layout.addWidget(self.buttons)

    def record(self):
        self.rec_kb_listener = keyboard.Listener(on_press=self.on_kb_click)
        self.rec_ms_listener = mouse.Listener(on_click=self.on_ms_click)
        self.rec_kb_listener.start()
        self.rec_ms_listener.start()
        self.rec_button.setText("Recording...")
        self.rec_button.setEnabled(False)
        self.rec_kb_listener.wait()
        self.rec_ms_listener.wait()

    def stop_rec(self):
        if self.rec_kb_listener is not None and self.rec_ms_listener is not None:
            self.rec_kb_listener.stop()
            self.rec_ms_listener.stop()
        self.rec_button.setText("Record")
        self.rec_button.setEnabled(True)

    def update_key(self, key: HotkeyType):
        self.key = key
        self.keyTypeLabel.setText(key[0])
        self.keyNameLabel.setText(key[1])

    def on_kb_click(self, key: keyboard.Key | keyboard.KeyCode | None):
        match key:
            case keyboard.Key():
                self.update_key(("keyboard", key.name))
            case keyboard.KeyCode():
                if key.char:
                    self.update_key(("keyboard", key.char))
        self.stop_rec()
    
    def on_ms_click(self, _x, _y, button: mouse.Button, pressed: bool):
        if pressed:
            self.update_key(("mouse", button.name))
            self.stop_rec()

    @classmethod
    def getNewHotKey(cls, parent: QWidget | None, cur_key: HotkeyType) -> HotkeyType:
        # return nothing since we register to global hotkey
        dialog = cls(parent, cur_key)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            return dialog.key
        else:
            return cur_key


class SingleKeyHotkeyListener:
    def __init__(self, input_key: HotkeyType, callback: Callable[[], None]):
        self.input_key = input_key
        self.callback = callback

        self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)

        self.keyboard_listener.start()
        self.mouse_listener.start()

    def stop_listeners(self):
        # should only be called when the main GUI stops
        self.keyboard_listener.stop()
        self.mouse_listener.stop()

    def on_key_press(self, key: keyboard.Key | keyboard.KeyCode | None):
        extracted_key: Optional[str] = None
        match key:
            case keyboard.Key():
                extracted_key = key.name
            case keyboard.KeyCode():
                if key.char:
                    extracted_key = key.char

        if ("keyboard", extracted_key) == self.input_key:
            self.callback()

    def on_mouse_click(self, _x, _y, button: mouse.Button, pressed: bool):
        if ("mouse", button.name) == self.input_key and pressed:
            self.callback()


class MainWindow(QMainWindow):
    def __init__(
        self,
        capture_window: CaptureWindow,
        tts_api: str = "http://localhost:47867/tts?format=wav&text=%s",
    ):
        super().__init__()

        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        self.capture_window = capture_window
        self.capture_window.show()

        self.toggleCaptureWindowCheckbox = QCheckBox("Show capture area", self)
        self.toggleCaptureWindowCheckbox.setChecked(True)
        self.toggleCaptureWindowCheckbox.stateChanged.connect(self.toggleCaptureWindow)

        # We use a rust-based TTS client, about 10x faster than python socket.connect
        tts_client = reqwest_wrapper.TTSClient()

        # Create helper function for TTS tasks
        self.tts_helper = TTSHelper(tts_client, tts_api)

        # Create a menu bar. We do this after tts_helper is created because the action changes tts_helper's members
        menuBar = QMenuBar(self)
        settingsMenu = menuBar.addMenu("Settings")
        assert settingsMenu is not None
        settingsMenu.addAction("Set TTS API URL", self.setTTSAPIWithDialog)
        settingsMenu.addAction("Set Hotkey", self.setHotKeyWithDialog)
        self.setMenuBar(menuBar)

        # Setup hotkeys
        self.hotkey_listener = SingleKeyHotkeyListener(("mouse", "middle"), self.start_ocr_tts_pipeline)

        # Add two more lights to indicate OCR & TTS worker status for debugging
        self.ocr_light = LightWidget(self, QColor(255, 232, 189), QColor("black"))
        self.tts_light = LightWidget(self, QColor(186, 227, 255), QColor("black"))

        # Create the list widget for displaying the text deque
        self.textListWidget = QListWidget(self)

        # Create queues & task workers for the OCR and TTS tasks
        self.ocr_queue = Queue()
        self.tts_queue = Queue()
        self.player_queue = Queue()
        self.ocr_worker = TaskWorker(self.ocr_queue, self.process_ocr, self.ocr_light)
        self.ocr_worker.task_finished.connect(self.onOcrFinished)
        self.tts_worker = TaskWorker(self.tts_queue, self.tts_helper, self.tts_light)
        self.tts_worker.task_finished.connect(self.onTtsFinished)
        self.player_worker = TaskWorker(self.player_queue, self.play_audio)
        self.player_worker.task_finished.connect(self.onPlayerFinished)

        self.ocr_worker.start()
        self.tts_worker.start()
        self.player_worker.start()

        # Layout
        layout = QHBoxLayout()
        layout.addWidget(self.toggleCaptureWindowCheckbox)
        layout.addWidget(self.ocr_light)
        layout.addWidget(self.tts_light)

        vertical_layout = QVBoxLayout()
        vertical_layout.addLayout(layout)
        vertical_layout.addWidget(self.textListWidget)

        # A central widget is needed to set a layout
        centralWidget = QWidget()
        centralWidget.setLayout(vertical_layout)
        self.setCentralWidget(centralWidget)

    def start_ocr_tts_pipeline(self):
        hwnd = int(self.capture_window.winId())

        # Use win32gui to get the window coordinates
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        region_screenshot = take_region_screenshot(left, top, right, bottom)

        self.ocr_queue.put(region_screenshot)

    def toggleCaptureWindow(self, state: int):
        if state == 2:
            self.capture_window.show()
        else:
            self.capture_window.hide()

    def setTTSAPIWithDialog(self):
        new_url = TTSAPIInputDialog.getNewURL(self, self.tts_helper)
        self.tts_helper.tts_api = new_url

    def setHotKeyWithDialog(self):
        old_key = self.hotkey_listener.input_key
        self.hotkey_listener.input_key = ("null", "")  # temporary disable
        new_key = HotKeyInputDialog.getNewHotKey(self, old_key)
        self.hotkey_listener.input_key = new_key

    @staticmethod
    def process_ocr(img: np.ndarray) -> Result[str, str]:
        logger.info("Processing OCR request...")
        return Ok(paddle_ocr_infer_fn(img))

    def onOcrFinished(self, res: Result[str, str]):
        # Update the UI with the OCR result
        match res:
            case Ok(text):
                if text:
                    item = self.addTextItem(text, "ttsing")
                    self.tts_queue.put((text, item))
            case Err(error_data):
                print(error_data)

    def onTtsFinished(self, res: Tuple[Result[bytes, str], QListWidgetItem]):
        # Update the UI with the TTS result
        result, item = res
        match result:
            case Ok(audio_data):
                self.setTextItemColor(item, "ready")
                self.player_queue.put((audio_data, item))
            case Err(error_data):
                self.setTextItemColor(item, "error")
                item.setText(error_data)

    @staticmethod
    def play_audio(task: Tuple[bytes, QListWidgetItem]) -> QListWidgetItem:
        audio_data, item = task
        data, fs = sf.read(BytesIO(audio_data))
        sd.play(data, fs)
        sd.wait()
        return item

    def onPlayerFinished(self, item: QListWidgetItem):
        self.setTextItemColor(item, "done")

    def closeEvent(self, _event) -> None:
        self.capture_window.close()

    def addTextItem(self, text: str, status: str) -> QListWidgetItem:
        # Create a new list item with the provided text
        item = QListWidgetItem(text)
        self.setTextItemColor(item, status)
        self.textListWidget.addItem(item)
        return item

    def setTextItemColor(self, item: QListWidgetItem, status: str):
        # Change the color of the list item based on its status
        color_dict = {
            "ttsing": (QColor(255, 232, 189), QColor("black")),
            "ready": (QColor(186, 227, 255), QColor("black")),
            "error": (QColor(255, 163, 181), QColor("black")),
            "done": (QColor(227, 255, 221), QColor("black")),
            "discarded": (QColor("grey"), QColor("black")),
        }
        background_color, text_color = color_dict.get(
            status, (QColor("white"), QColor("black"))
        )
        item.setBackground(background_color)
        item.setForeground(text_color)


if __name__ == "__main__":
    app = QApplication([])
    capture_window = CaptureWindow()

    status_bar_window = MainWindow(capture_window)

    status_bar_window.show()

    app.exec()
