# from tkinter import Tk, Frame

# root = Tk()
# frame = Frame(root, width=100, height=100, highlightthickness=10, highlightbackground="black", bg="white")
# frame.pack(expand=True, fill="both")
# root.wm_attributes("-transparentcolor", "white")
# root.config(bg="white")
# root.mainloop()

from PyQt6.QtCore import QEvent, Qt, QTimer, QBuffer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication, QMainWindow, QDoubleSpinBox, QHBoxLayout, QCheckBox, QListWidget, QListWidgetItem
from PyQt6.QtGui import QCloseEvent, QPaintEvent, QPainter, QColor, QMouseEvent, QCursor, QScreen
from screenshot_utils import take_region_screenshot
from ocr_infer import ocr
from typing import Optional, Callable
import win32gui
import win32ui
from ctypes import windll
from PIL import Image, ImageDraw
from io import BytesIO


class CaptureWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.border_color = QColor(255, 0, 0)  # Red color
        self.border_width = 5  # Border width in pixels
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.grab_flags = [False] * 4  # Share grab status between mouse event callbacks

    def paintEvent(self, event):
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)  # Set the size of the light indicator
        self.light_on = False
        self.on_color = QColor('green')
        self.off_color = QColor('red')

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


class StatusBarWindow(QMainWindow):
    def __init__(self, capture_window: CaptureWindow):
        super().__init__()

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

        # Create the list widget for displaying the text deque
        self.textListWidget = QListWidget(self)

        # Layout
        layout = QHBoxLayout()
        layout.addWidget(self.toggleCaptureWindowCheckbox)
        layout.addWidget(self.toggleRunCheckbox)
        layout.addWidget(QLabel("Capture Duration (s):"))
        layout.addWidget(self.captureDurationSpinBox)
        layout.addWidget(self.light_indicator)
        layout.addWidget(self.textListWidget)

        # A central widget is needed to set a layout
        centralWidget = QWidget()
        centralWidget.setLayout(layout)
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

        # add changed check later
        region_text = ocr(region_screenshot)
        self.addTextItem(region_text, "pending")

    def closeEvent(self, _event) -> None:
        self.capture_window.close()

    def addTextItem(self, text, status):
        # Create a new list item with the provided text
        item = QListWidgetItem(text)
        self.setTextItemColor(item, status)
        self.textListWidget.addItem(item)

    def setTextItemColor(self, item, status):
        # Change the color of the list item based on its status
        color_dict = {
            'pending': QColor('grey'),
            'processing': QColor('blue'),
            'reading': QColor('green'),
            'done': QColor('white')  # or any color that indicates completion
        }
        item.setBackground(color_dict.get(status, QColor('white')))


if __name__ == "__main__":
    app = QApplication([])
    capture_window = CaptureWindow()

    status_bar_window = StatusBarWindow(capture_window)

    status_bar_window.show()

    app.exec()
