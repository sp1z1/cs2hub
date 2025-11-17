# core/signals.py
from PyQt6.QtCore import pyqtSignal, QObject

class FirebaseSignals(QObject):
    """Объект для безопасной передачи данных из потока Firebase в главный поток Qt."""
    guide_changed = pyqtSignal(str, dict)
    guides_structure_changed = pyqtSignal()