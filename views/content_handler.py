# views/content_handler.py (Полностью обновленный код)

import logging
import markdown
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from core.firebase_service import (
    get_guide_content_firestore_by_structure_id as get_guide_content,
    save_guide_content_firestore_by_structure_id as save_guide_firestore,
)


class ContentHandlerMixin:
    def init_content(self):
        self.current_guide_fn = None
        self.original_content = ""
        self.content_changed = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_webview)
    
    def load_guide_by_node_id(self, node_id: str):
        if self.content_changed and self.is_editable:
            reply = QMessageBox.question(self, "Несохранённые изменения",
                                         "Сохранить перед переключением?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Yes:
                if not self.save_current_guide(): 
                    return

        data = get_guide_content(node_id)
        if data:
            self.current_guide_fn = node_id
            self.original_content = data.get("content", "")
            self.current_last_modified = data.get("last_modified") 
            
            # Загружаем контент в редактор ТОЛЬКО если мы уже в режиме редактирования
            if hasattr(self, 'is_editing_mode') and self.is_editing_mode:
                self.editor.setPlainText(self.original_content)
                
            self.update_webview()
            self.content_changed = False
            
            # Обновление иконок и кнопок
            if hasattr(self, 'update_save_status_icons'):
                self.update_save_status_icons()

            # Скрытие кнопки Перезагрузить после успешной загрузки
            if hasattr(self, 'btn_reload'):
                 self.btn_reload.setVisible(False)
            
            self.set_status_ok(f"Гайд загружен", 2000)
        else:
            self.editor.clear()
            self.webview.setHtml("")
            self.current_guide_fn = None
            self.current_last_modified = None 

    def update_webview(self):
        # Показываем контент из редактора, если мы в режиме редактирования, иначе - оригинальный контент
        md = self.editor.toPlainText() if self.is_editing_mode else self.original_content
        
        # Если контент пуст, ничего не показываем
        if not md:
            self.webview.setHtml("")
            return
            
        html = markdown.markdown(md, extensions=["fenced_code", "tables", "toc", "nl2br"])
        styled = f"""
        <html><head><style>
            body {{background:#1a1a1a; color:#e0e0e0; padding:30px; font-family:Segoe UI; line-height:1.6;}}
            h1,h2,h3 {{color:#00ff85;}} a {{color:#00ff85;}}
            pre,code {{background:#232323; border-radius:4px;}}
            table,th,td {{border:1px solid #444; border-collapse:collapse; padding:8px;}}
            th {{background:#333;}}
        </style></head><body>{html}</body></html>
        """
        self.webview.setHtml(styled)

    def on_content_changed(self):
        if not self.is_editable:
            return
        changed = self.editor.toPlainText() != self.original_content
        self.content_changed = changed
        
        # Обновление иконок и кнопок
        if hasattr(self, 'update_save_status_icons'):
            self.update_save_status_icons()
        if self.is_editing_mode: 
            self.update_webview() # <-- ЭТО ОБЕСПЕЧИТ ПОКАЗ ТЕКСТА НА ПРЕВЬЮ

    def cancel_edit(self):
        """Отменяет изменения контента."""
        if self.current_guide_fn and self.is_editable:
            # Загружаем оригинальный контент в редактор
            self.editor.setPlainText(self.original_content)
            self.content_changed = False
            
            # Обновление иконок и кнопок
            if hasattr(self, 'update_save_status_icons'):
                self.update_save_status_icons()

            # Скрытие кнопки Перезагрузить
            if hasattr(self, 'btn_reload'):
                 self.btn_reload.setVisible(False)
            
            self.update_webview()
            self.set_status_ok("Изменения отменены", 2000)

    def save_current_guide(self):
        """Сохраняет контент с проверкой конфликта."""
        if not self.current_guide_fn or not self.is_editable:
            return False
        
        new_content = self.editor.toPlainText()
        
        # Передаем старую метку времени для проверки конфликта в Firestore
        result = save_guide_firestore(
            self.current_guide_fn, 
            new_content, 
            self.current_last_modified
        )

        if result is True:
            # УСПЕХ: Обновляем локальное состояние
            self.original_content = new_content
            self.content_changed = False
            
            self.set_status_ok("Сохранено", 3000)
            self.update_webview()
            
            # Перезагружаем гайд, чтобы получить новую метку SERVER_TIMESTAMP
            self.load_guide_by_node_id(self.current_guide_fn)
            return True
            
        elif result == "conflict":
            # КОНФЛИКТ: Сообщаем пользователю и предлагаем перезагрузить
            QMessageBox.warning(
                self, 
                "Конфликт сохранения", 
                "Этот гайд был изменен другим пользователем. Ваши изменения не сохранены. "
                "Ваш черновик остается в редакторе. Нажмите 'Перезагрузить' для загрузки последней версии с сервера (ваши изменения будут потеряны)."
            )
            self.set_status_error("Конфликт! Не сохранено.", 5000)
            
            # Показываем кнопку "Перезагрузить"
            if hasattr(self, 'btn_reload'):
                 self.btn_reload.setVisible(True)
                 
            return False 
            
        else: # Общая ошибка (False)
            QMessageBox.critical(self, "Ошибка сохранения", "Произошла ошибка при сохранении контента.")
            self.set_status_error("Ошибка сохранения.", 5000)
            return False