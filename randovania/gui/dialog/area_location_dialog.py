import json
from pathlib import Path

from PySide2.QtCore import QRect, QPoint, QSize
from PySide2.QtGui import QPixmap, QMouseEvent
from PySide2.QtWidgets import QMainWindow, QLabel, QWidget, QRadioButton, QPushButton, QDialog, QFileDialog, QMessageBox

from randovania.game_description.area import Area


class MovableRadioButton(QRadioButton):
    is_dragging = False

    def mousePressEvent(self, event: QMouseEvent):
        self.is_dragging = True
        self.offset = event.pos()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.is_dragging:
            self.move(self.pos() + event.pos() - self.offset)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.is_dragging = False


class AreaLocationDialog(QDialog):
    def __init__(self, area: Area, image_path: Path):
        super().__init__()

        self.area = area
        self.image_path = image_path

        central_widget = QWidget(self)

        label = QLabel(central_widget)
        pixmap = QPixmap(str(image_path))
        label.setPixmap(pixmap)
        label.setGeometry(QRect(QPoint(0, 0), pixmap.size()))

        x_distance = (pixmap.width() - 50) / len(area.nodes)

        self.radios = []
        for i, node in enumerate(area.nodes):
            radio = MovableRadioButton(central_widget)
            radio.setText(node.name)
            radio.setGeometry(QRect(QPoint(50 + i * x_distance, 50), radio.size()))
            self.radios.append(radio)

        save_button = QPushButton(central_widget)
        save_button.setText("Save Positions")
        save_button.clicked.connect(self._save_positions)
        save_button.setGeometry(QRect(QPoint(0, pixmap.height()), save_button.size()))

        load_button = QPushButton(central_widget)
        load_button.setText("Load Positions")
        load_button.clicked.connect(self._load_positions)
        load_button.setGeometry(QRect(QPoint(save_button.width() + 10, save_button.y()), load_button.size()))

        central_widget.setMinimumSize(pixmap.width(), pixmap.height() + 30)
        self.resize(central_widget.size())

    def _save_positions(self):
        new_path = self.image_path.parent.joinpath(self.image_path.stem + ".positions.json")
        with new_path.open("w") as f:
            json.dump({
                "area_asset_id": self.area.area_asset_id,
                "area_name": self.area.name,
                "image_name:": self.image_path.name,
                "positions": [
                    {"x": radio.x(), "y": radio.y()}
                    for radio in self.radios
                ]
            }, f)

    def _load_positions(self):
        open_result = QFileDialog.getOpenFileName(self, caption="Select previously exported image sizes.",
                                                  filter="*.positions.json")
        if not open_result or open_result == ("", ""):
            return

        with open(open_result[0]) as file_to_load:
            loaded_data = json.load(file_to_load)

        if len(loaded_data["positions"]) != len(self.radios):
            QMessageBox.critical(self,
                                 "Invalid positions file",
                                 ("Provided positions file has {} positions instead of {}. "
                                  "It's also for area {}, while {} is being edited.").format(
                                     len(loaded_data["positions"]),
                                     len(self.radios),
                                     loaded_data["area_name"],
                                     self.area.name
                                 ))
            return

        for new_position, radio in zip(loaded_data["positions"], self.radios):
            radio.move(new_position["x"], new_position["y"])