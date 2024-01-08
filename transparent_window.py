from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication, QMainWindow, QDoubleSpinBox, QHBoxLayout, QCheckBox, QListWidget, QListWidgetItem
from PyQt6.QtGui import QPainter, QColor, QMouseEvent
from screenshot_utils import take_region_screenshot
from queue import Queue
import win32gui
import numpy as np
from typing import Optional, Callable, Any, Dict, Tuple
import requests
from result import Result, Ok, Err
import json
from functools import partial
import sounddevice as sd
import soundfile as sf
from io import BytesIO
from threading import Lock
from skimage.metrics import structural_similarity
import pickle
from collections import deque
import editdistance


def run_flask_app():
    from ocr_server import app
    app.run()


class CaptureWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.border_color = QColor(255, 0, 0)  # Red color
        self.border_width = 10  # Border width in pixels
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
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
            bottom_edge = abs(self.mousePressPos.y() - rect.bottom()) < self.border_width
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
                rect.setLeft(min(rect.left() + dx, rect.right() - (self.border_width << 1)))
            if right_edge:
                rect.setRight(max(rect.right() + dx, rect.left() + (self.border_width << 1)))
            if top_edge:
                rect.setTop(min(rect.top() + dy, rect.bottom() - (self.border_width << 1)))
            if bottom_edge:
                rect.setBottom(max(rect.bottom() + dy, rect.top() + (self.border_width << 1)))

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

    def __init__(self, task_queue: Queue, task_handler: Callable[..., Any], light_indicator: Optional[LightWidget]=None, lock=None) -> None:
        super().__init__()
        self.task_queue = task_queue
        self.task_handler = task_handler
        self.running = True
        self.light_indicator = light_indicator
        self.lock = lock

    def run(self) -> None:
        while self.running:
            if self.task_queue.empty():
                self.msleep(50)
            else:
                if self.light_indicator is not None:
                    self.light_indicator.turn_on()
                if self.lock is not None:
                    with self.lock:
                        task = self.task_queue.get()
                else:
                    task = self.task_queue.get()
                result = self.task_handler(task)
                self.task_queue.task_done()
                if self.light_indicator is not None:
                    self.light_indicator.turn_off()
                self.task_finished.emit(result)

    def stop(self):
        self.running = False


class MainWindow(QMainWindow):
    def __init__(self, capture_window: CaptureWindow, tts_api: str="http://localhost:47867/tts?format=wav&text=%s", ocr_api: str="http://localhost:48080/ocr"):
        super().__init__()

        self.tts_api = tts_api
        self.ocr_api = ocr_api

        self.tts_recent_text = deque(maxlen=10)

        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        self.capture_window = capture_window
        self.capture_window.show()
        self.label = QLabel("Hello World")
        self.setCentralWidget(self.label)

        self.toggleCaptureWindowCheckbox = QCheckBox("Capture window", self)
        self.toggleCaptureWindowCheckbox.setChecked(True)
        self.toggleCaptureWindowCheckbox.stateChanged.connect(self.toggleCaptureWindow)

        # Create a checkbox
        self.toggleRunCheckbox = QCheckBox("Run", self)
        self.toggleRunCheckbox.stateChanged.connect(self.toggleRun)

        # Create a double spin box for capture duration
        self.captureDurationSpinBox = QDoubleSpinBox(self)
        self.captureDurationSpinBox.setRange(0.2, 60.0)  # From 0.2s to 60s
        self.captureDurationSpinBox.setSingleStep(0.1)  # Increment by 0.1s
        self.captureDurationSpinBox.setDecimals(1)  # One decimal place
        self.captureDurationSpinBox.setValue(0.5)  # Default value
        self.captureDurationSpinBox.valueChanged.connect(self.captureDurationChanged)

        self.queryTimer = QTimer(self)
        self.queryTimer.timeout.connect(self.performRollingQuery)

        # Create the light indicator
        self.light_indicator = LightWidget(self)
        self.light_indicator.turn_off()  # Initially off

        # Timer to control the light duration
        self.lightTimer = QTimer(self)
        self.lightTimer.setInterval(200)  # Light duration in milliseconds
        self.lightTimer.setSingleShot(True)  # Only trigger once each time it's started
        self.lightTimer.timeout.connect(self.light_indicator.turn_off)

        # Add two more lights to indicate OCR & TTS worker status for debugging
        self.ocr_light = LightWidget(self, QColor(255, 232, 189), QColor('black'))
        self.tts_light = LightWidget(self, QColor(186, 227, 255), QColor('black'))

        # Create the list widget for displaying the text deque
        self.textListWidget = QListWidget(self)

        # for TTS dedup, we need to keep track of the last text, using lock
        self.tts_que_lock = Lock()
        self.last_tts_text: Optional[str] = None

        # Create queues & task workers for the OCR and TTS tasks
        self.ocr_queue = Queue()
        self.tts_queue = Queue()
        self.player_queue = Queue()
        self.ocr_worker = TaskWorker(self.ocr_queue, partial(self.process_ocr, self.ocr_api), self.ocr_light)
        self.ocr_worker.task_finished.connect(self.onOcrFinished)
        self.tts_worker = TaskWorker(self.tts_queue, partial(self.process_tts, self.tts_api), self.tts_light, self.tts_que_lock)
        self.tts_worker.task_finished.connect(self.onTtsFinished)
        self.player_worker = TaskWorker(self.player_queue, self.send_audio)
        self.player_worker.task_finished.connect(self.onPlayerFinished)

        self.ocr_worker.start()
        self.tts_worker.start()
        self.player_worker.start()

        # cache of last screenshot
        self.last_screenshot: np.ndarray = np.zeros((1, 1, 3), dtype=np.uint8)

        # Layout
        layout = QHBoxLayout()
        layout.addWidget(self.toggleCaptureWindowCheckbox)
        layout.addWidget(self.toggleRunCheckbox)
        layout.addWidget(QLabel("Capture Duration (s):"))
        layout.addWidget(self.captureDurationSpinBox)
        layout.addWidget(self.light_indicator)
        layout.addWidget(self.ocr_light)
        layout.addWidget(self.tts_light)

        vertical_layout = QVBoxLayout()
        vertical_layout.addLayout(layout)
        vertical_layout.addWidget(self.textListWidget)

        # A central widget is needed to set a layout
        centralWidget = QWidget()
        centralWidget.setLayout(vertical_layout)
        self.setCentralWidget(centralWidget)

    def toggleRun(self, state: int):
        if state == 2:
            print("Starting rolling query..., interval:", self.captureDurationSpinBox.value())
            self.queryTimer.start(int(self.captureDurationSpinBox.value() * 1000))  # Start the timer
        else:
            self.queryTimer.stop()

    def toggleCaptureWindow(self, state: int):
        if state == 2:
            self.capture_window.show()
        else:
            self.capture_window.hide()

    def captureDurationChanged(self, value):
        # Handle the change in capture duration value
        # This function can signal the capture functionality to update its timing
        # Update the timer interval
        print(f"Capture duration set to: {value} seconds")
        if self.toggleRunCheckbox.isChecked():
            self.queryTimer.start(int(value * 1000))  # QTimer expects milliseconds

    def performRollingQuery(self):
        # Call the capture window function and set the color of the indication light
        # This is where you'd trigger the screen capture and update the UI
        self.light_indicator.turn_on()
        self.lightTimer.start()  # Start the timer that will turn off the light after the set interval

        hwnd = int(self.capture_window.winId())

        # Use win32gui to get the window coordinates
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        region_screenshot = take_region_screenshot(left, top, right, bottom)

        if self.last_screenshot is not None:
            # if the screenshot is similar enough, don't bother doing OCR again, but how do we know if it's similar enough?
            if self.last_screenshot.shape == region_screenshot.shape:
                if structural_similarity(self.last_screenshot, region_screenshot, channel_axis=-1) < 0.9:
                    self.ocr_queue.put(region_screenshot)
            else:
                self.ocr_queue.put(region_screenshot)
        self.last_screenshot = region_screenshot

    @staticmethod
    def process_ocr(ocr_api: str, img: np.ndarray) -> Result[str, str]:
        print("Processing OCR request...")
        def inner(req_url: str) -> Result[str, str]:
            try:
                response = requests.post(req_url, files={"file": pickle.dumps(img)})
                if response.status_code == 200:
                    return Ok(response.json().get("result", ""))
                else:
                    return Err(json.dumps(response.json().get("error", "")))
            except requests.exceptions.RequestException as e:
                return Err(str(e))
        res = inner(ocr_api)
        return res


    def onOcrFinished(self, res: Result[str, str]):
        # Update the UI with the OCR result
        match res:
            case Ok(text):
                # with self.tts_que_lock:
                #     agg_text = text
                #     for que_text, _ in self.tts_queue.queue:
                #         if agg_text in que_text:
                #             agg_text = que_text
                #     to_be_removed = []
                #     for que_text, item in self.tts_queue.queue:
                #         if que_text in agg_text:
                #             to_be_removed.append((que_text, item))
                #         if editdistance.eval(que_text, agg_text) < 5:
                #             to_be_removed.append((que_text, item))
                #     for task in to_be_removed:
                #         self.tts_queue.queue.remove(task)
                #         _, item = task
                #         self.setTextItemColor(item, "discarded")
                if text:
                    for recent_text in self.tts_recent_text:
                        if editdistance.eval(recent_text, text) - abs(len(recent_text) - len(text)) < 5:
                            return
                    self.tts_recent_text.append(text)
                    item = self.addTextItem(text, "ttsing")
                    self.tts_queue.put((text, item))
            case Err(error_data):
                print(error_data)

    @staticmethod
    def process_tts(tts_api: str, task: Tuple[str, QListWidgetItem]) -> Tuple[Result[bytes, str], QListWidgetItem]:
        text, item = task
        print("Processing TTS request..:", text)
        def inner(req_url: str) -> Result[bytes, str]:
            try:
                response = requests.get(req_url)
                if response.status_code == 200 and response.headers['Content-Type'] == 'audio/wav':
                    # Success - process the audio data
                    audio_data = response.content
                    return Ok(audio_data)
                else:
                    # Failure - process the error
                    error_data = response.json()
                    return Err(json.dumps(error_data))
            except requests.exceptions.RequestException as e:
                return Err(str(e))
        res = inner(tts_api % text)
        return res, item

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
    def send_audio(task: Tuple[bytes, QListWidgetItem]) -> QListWidgetItem:
        audio_data, item = task
        data, fs = sf.read(BytesIO(audio_data))
        sd.play(data, fs)
        sd.wait()
        return item

    def onPlayerFinished(self, item: QListWidgetItem):
        self.setTextItemColor(item, "done")

    def closeEvent(self, _event) -> None:
        self.capture_window.close()

    def addTextItem(self, text, status) -> QListWidgetItem:
        # Create a new list item with the provided text
        item = QListWidgetItem(text)
        self.setTextItemColor(item, status)
        self.textListWidget.addItem(item)
        return item

    def setTextItemColor(self, item, status):
        # Change the color of the list item based on its status
        color_dict = {
            'ttsing': (QColor(255, 232, 189), QColor('black')),
            'ready': (QColor(186, 227, 255), QColor('black')),
            'error': (QColor(255, 163, 181), QColor('black')),
            'done': (QColor(227, 255, 221), QColor('black')),
            'discarded': (QColor('grey'), QColor('black')),
        }
        background_color, text_color = color_dict.get(status, (QColor('white'), QColor('black')))
        item.setBackground(background_color)
        item.setForeground(text_color)


if __name__ == "__main__":
    app = QApplication([])
    capture_window = CaptureWindow()

    status_bar_window = MainWindow(capture_window)

    status_bar_window.show()

    app.exec()
