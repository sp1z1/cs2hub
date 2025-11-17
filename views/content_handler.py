# views/content_handler.py
import logging
import markdown
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from core.firebase_service import (
    get_guide_content_firestore_by_structure_id as get_guide_content,
    save_guide_content_by_structure_id as save_guide_firestore,
)


class ContentHandlerMixin:
    def init_content(self):
        self.current_guide_fn = None
        self.original_content = ""
        self.content_changed = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_webview)
        self.action_save = None
        self.btn_cancel = None
        # self.is_editable, self.editor, self.webview должны быть инициализированы в MainWindow

    def load_guide_by_node_id(self, node_id: str):
        if self.content_changed and self.is_editable:
            reply = QMessageBox.question(self, "Несохранённые изменения",
                                         "Сохранить перед переключением?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Yes:
                # save_current_guide теперь должен возвращать True/False
                if not self.save_current_guide(): 
                    # Если сохранение не удалось, остаемся на текущем гайде
                    return

        data = get_guide_content(node_id)
        if data:
            self.current_guide_fn = node_id
            self.original_content = data.get("content", "")
            self.editor.setPlainText(self.original_content)
            self.update_webview()
            self.content_changed = False
            
            if self.action_save:
                self.action_save.setEnabled(False)
            
            # Внимание: Вызов self.toggle_edit_mode(False) происходит в MainWindow.load_guide_by_node_id, 
            # обеспечивая переключение в режим просмотра
            
            self.set_status_ok(f"Гайд загружен", 2000)
        else:
            self.editor.clear()
            self.webview.setHtml("")
            self.current_guide_fn = None

    def update_webview(self):
        md = self.editor.toPlainText()
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
        if self.action_save:
            self.action_save.setEnabled(changed)
        # Видимость кнопки Отмена должна быть False при отсутствии изменений 
        # (но она также контролируется toggle_edit_mode)
        if self.btn_cancel:
            self.btn_cancel.setVisible(changed)

    def cancel_edit(self):
        """Отменяет изменения контента. Переключение режима делегируется MainWindow."""
        if self.current_guide_fn and self.is_editable:
            self.editor.setPlainText(self.original_content)
            self.content_changed = False
            if self.action_save:
                self.action_save.setEnabled(False)
            
            # Удалено: self.btn_cancel.hide()
            
            self.update_webview()
            self.set_status_ok("Изменения отменены", 2000)

    def save_current_guide(self):
        """Сохраняет контент. Переключение режима делегируется MainWindow."""
        if not self.current_guide_fn or not self.is_editable:
            return False
        
        if save_guide_firestore(self.current_guide_fn, self.editor.toPlainText()):
            self.original_content = self.editor.toPlainText()
            self.content_changed = False
            if self.action_save:
                self.action_save.setEnabled(False)
            
            # Удалено: self.btn_cancel.hide()
            
            self.set_status_ok("Сохранено", 3000)
            self.update_webview()
            return True
        return False