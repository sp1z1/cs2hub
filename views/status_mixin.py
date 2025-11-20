# views/status_mixin.py
import logging
from PyQt6.QtWidgets import QMessageBox, QApplication
from PyQt6.QtGui import QCloseEvent # Добавлен импорт для type hinting


class StatusMixin:
    def set_status_ok(self, msg: str, timeout: int = 2000):
        self.statusBar().setStyleSheet("color:#00ff85;")
        self.statusBar().showMessage(msg, timeout)

    def set_status_error(self, msg: str, timeout: int = 5000):
        self.statusBar().setStyleSheet("color:#ff6b6b;")
        self.statusBar().showMessage("Ошибка: " + msg, timeout)

    def logout(self):
        """
        Выход из аккаунта: скрывает главное окно и возвращает управление в основной цикл 
        для показа окна входа.
        """
        
        # 1. Проверка на несохраненные изменения
        if hasattr(self, 'content_changed') and self.content_changed and hasattr(self, 'is_editable') and self.is_editable:
            reply = QMessageBox.question(
                self, 
                "Несохраненные изменения", 
                "У вас есть несохраненные изменения. Вы уверены, что хотите выйти?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return # Отмена выхода
        
        # 2. 🔥 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 1: Останавливаем слушатели
        if hasattr(self, 'stop_realtime_listeners'):
            self.stop_realtime_listeners()
            
        # 3. Скрываем текущее окно (MainWindow)
        self.hide() 

        # 4. Закрываем родительский LoginDialog, если он еще существует
        if hasattr(self, 'parent_dialog') and self.parent_dialog:
            self.parent_dialog.close() 

        # 5. 🔥 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 2: Останавливаем внутренний цикл app.exec().
        # ЭТО ТО, ЧТО РЕШАЕТ ПРОБЛЕМУ "окна нету, но приложение не закрывается".
        QApplication.exit() 
        
        # 6. Закрываем MainWindow для очистки ресурсов.
        self.close()

    def closeEvent(self, event: QCloseEvent):
        """Обработка закрытия окна крестиком или через системное меню."""
        # 1. Проверка на несохраненные изменения
        if hasattr(self, 'content_changed') and self.content_changed and hasattr(self, 'is_editable') and self.is_editable:
            reply = QMessageBox.question(self, "Выход", "Сохранить изменения?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.StandardButton.Yes:
                self.save_current_guide()
                # Если сохранение не удалось, отменяем закрытие
                if self.content_changed:
                    event.ignore()
                    return
        
        # 2. 🔥 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 3: Останавливаем слушателей при закрытии крестиком
        if hasattr(self, 'stop_realtime_listeners'):
            self.stop_realtime_listeners()
            
        # 3. Полное завершение приложения.
        # quit() завершает приложение полностью, что подходит для закрытия крестиком.
        QApplication.quit()
        event.accept()
    def update_save_status_icons(self):
        """Обновляет состояние кнопок Сохранить и Отмена на основе self.content_changed."""
        
        # 0. 🔥 НОВОЕ ИСПРАВЛЕНИЕ: Выход, если пользователь не имеет прав на редактирование.
        if not self.is_editable:
            # Для не-редакторов мы просто сбрасываем статус-бар,
            # и кнопки Сохранить/Отмена не будут существовать (или будут невидимы).
            self.statusBar().clearMessage()
            return
            
        # 1. Проверка на возможность сохранения (теперь только для редакторов)
        # Поскольку мы уже проверили is_editable, здесь остается только проверка current_guide_fn.
        if not self.current_guide_fn:
            # Отключаем кнопки, если сохранение невозможно
            if hasattr(self, 'action_save') and self.action_save:
                self.action_save.setEnabled(False)
            if hasattr(self, 'action_cancel') and self.action_cancel:
                self.action_cancel.setEnabled(False)
            return

        # 2. !!! КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ ДЛЯ СОХРАНЕНИЯ !!!
        can_save = self.content_changed
        
        if hasattr(self, 'action_save') and self.action_save:
            # Кнопка "Сохранить" включена, только если есть изменения
            self.action_save.setEnabled(can_save)
        
        if hasattr(self, 'action_cancel') and self.action_cancel:
            # Кнопка "Отмена" включена, только если есть изменения
            self.action_cancel.setEnabled(can_save)

        # 3. Обновление статуса в статус-баре
        if can_save:
            self.set_status_error("Несохраненные изменения", 0) 
        else:
            self.statusBar().clearMessage()