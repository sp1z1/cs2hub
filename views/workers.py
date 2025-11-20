# views/workers.py
from PyQt6.QtCore import QThread, pyqtSignal
import logging
from core.firebase_service import (
    get_all_users_firestore, 
    set_user_role_firestore, 
    get_structure_metadata,
    delete_node_recursively
)

class DataLoaderThread(QThread):
    """Универсальный поток для загрузки данных"""
    data_loaded = pyqtSignal(object) # Возвращает данные (dict или list)
    error_occurred = pyqtSignal(str)

    def __init__(self, fetch_function, *args):
        super().__init__()
        self.fetch_function = fetch_function
        self.args = args

    def run(self):
        try:
            data = self.fetch_function(*self.args)
            self.data_loaded.emit(data)
        except Exception as e:
            logging.error(f"Thread Error: {e}")
            self.error_occurred.emit(str(e))

class ActionWorkerThread(QThread):
    """Поток для выполнения действий (сохранение, удаление)"""
    finished = pyqtSignal(bool, str) # Success, Message

    def __init__(self, action_function, success_msg, fail_msg, *args):
        super().__init__()
        self.func = action_function
        self.success_msg = success_msg
        self.fail_msg = fail_msg
        self.args = args

    def run(self):
        try:
            result = self.func(*self.args)
            if result:
                self.finished.emit(True, self.success_msg)
            else:
                self.finished.emit(False, self.fail_msg)
        except Exception as e:
            self.finished.emit(False, f"Ошибка: {str(e)}")