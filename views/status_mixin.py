# views/status_mixin.py
import logging
from PyQt6.QtWidgets import QMessageBox, QApplication


class StatusMixin:
    def set_status_ok(self, msg: str, timeout: int = 2000):
        self.statusBar().setStyleSheet("color:#00ff85;")
        self.statusBar().showMessage(msg, timeout)

    def set_status_error(self, msg: str, timeout: int = 5000):
        self.statusBar().setStyleSheet("color:#ff6b6b;")
        self.statusBar().showMessage("Ошибка: " + msg, timeout)

    def logout(self):
        """Выход из аккаунта: скрывает главное окно и показывает окно входа."""
        
        if self.content_changed:
            reply = QMessageBox.question(
                self, 
                "Несохраненные изменения", 
                "У вас есть несохраненные изменения. Вы уверены, что хотите выйти?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return # Отмена выхода
        
        # 1. Скрываем текущее окно (MainWindow)
        self.hide() 

        # 2. 🔥 ИЗМЕНЕНИЕ: Закрываем родительский LoginDialog
        # Это гарантирует, что старый экземпляр не будет висеть в фоне.
        if self.parent_dialog:
            self.parent_dialog.close() 

        # 3. 🔥 ИЗМЕНЕНИЕ: Останавливаем внутренний цикл app.exec().
        # Это возвращает управление в цикл while True в main.py для перезапуска.
        QApplication.exit() 
        
        # 4. Закрываем MainWindow для очистки ресурсов.
        self.close()

    def closeEvent(self, event):
        if self.content_changed and self.is_editable:
            reply = QMessageBox.question(self, "Выход", "Сохранить изменения?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.StandardButton.Yes:
                self.save_current_guide()
                if self.content_changed:
                    event.ignore()
                    return
        
        # Оставляем QApplication.quit() для ПОЛНОГО завершения приложения,
        # если пользователь закрыл его крестиком.
        QApplication.quit()
        event.accept()