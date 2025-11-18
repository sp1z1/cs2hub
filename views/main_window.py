# views/main_window.py
import logging
import markdown
import qtawesome as qta
from typing import TYPE_CHECKING, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QLineEdit,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit, QToolBar,
    QMessageBox, QPushButton, QSizePolicy
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtWebEngineWidgets import QWebEngineView

from core.firebase_service import (
    get_structure_metadata,
    # Импорты для firestore, хотя их использование делегируется миксинам
    get_guide_content_firestore_by_structure_id as get_guide_content,
    save_guide_content_by_structure_id as save_guide_firestore,
    create_new_node, rename_node, delete_node_recursively,
    DEFAULT_GUIDE_CONTENT
)
from views.web_engine import ExternalLinkPage
from views.admin_dialogs import UserManagementDialog, GuideManagementDialog

if TYPE_CHECKING:
    from views.auth_dialogs import LoginDialog

# Миксины
from .tree_handler import TreeHandlerMixin
from .content_handler import ContentHandlerMixin
from .admin_mixin import AdminMixin
from .status_mixin import StatusMixin


class MainWindow(TreeHandlerMixin, ContentHandlerMixin, AdminMixin, StatusMixin, QMainWindow):
    def __init__(self, username: str, user_role: str, parent: 'LoginDialog' = None):
        super().__init__()
        self.parent_dialog: Optional['LoginDialog'] = parent
        self.username: str = username
        self.user_role: str = user_role
        self.is_editable: bool = user_role in ('editor', 'admin')
        self.is_editing_mode: bool = False # Флаг для нового режима

        self.init_tree() # Инициализация переменных для миксинов
        self.init_content()

        self.setup_ui()
        self.setup_toolbar()
        self.apply_style()
        
        # 1. Сначала открывается блок просмотра
        self.load_guide_by_node_id("root_info") 
        self.toggle_edit_mode(False) # Убедимся, что начинаем в режиме просмотра

        self.update_user_info_in_toolbar()
        self.start_realtime_listeners()

    def setup_ui(self):
        self.setWindowTitle("CS2 Guide Hub")
        self.setMinimumSize(1200, 800)
        self.setWindowIcon(qta.icon("fa5s.book", color="#00ff85"))

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # === Левая панель (Sidebar) ===
        sidebar = QWidget()
        sidebar.setFixedWidth(320)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по гайдам...")
        self.search_input.setClearButtonEnabled(True)
        # Подключение поиска (предполагается таймер в init_tree из миксина)
        self.search_input.textChanged.connect(lambda: self.search_timer.start(300)) 
        sidebar_layout.addWidget(self.search_input)

        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)
        self.tree.itemDoubleClicked.connect(self.on_tree_item_double_clicked)
        sidebar_layout.addWidget(self.tree)

        self.main_splitter.addWidget(sidebar)

        # === Правая панель (Content Area) ===
        self.content_area = QWidget()
        content_layout = QVBoxLayout(self.content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Главный сплиттер для области контента (редактор/просмотр) - Горизонтальный
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setHandleWidth(1)

        # Редактор (слева)
        self.editor = QTextEdit()
        self.editor.textChanged.connect(self.on_content_changed)

        # Просмотр (справа)
        self.webview = QWebEngineView()
        self.webview.setPage(ExternalLinkPage())

        self.content_splitter.addWidget(self.editor)
        self.content_splitter.addWidget(self.webview)
        self.content_splitter.setSizes([500, 500]) # Стартовые размеры

        content_layout.addWidget(self.content_splitter)
        self.main_splitter.addWidget(self.content_area)
        self.main_splitter.setSizes([320, 880])

    def toggle_edit_mode(self, enabled: bool):
        """Включает/выключает режим редактирования, контролирует сплиттер и кнопки."""
        self.is_editing_mode = enabled

        # Редактор виден только в режиме редактирования
        self.editor.setVisible(enabled)

        # Управление размерами сплиттера: 50/50 в режиме редактирования, 0/100 в режиме просмотра
        if enabled:
            # Режим редактирования: [Редактор (50%) | Просмотр (50%)]
            self.content_splitter.setSizes([600, 600])
        else:
            # Режим просмотра: [Редактор (0%) | Просмотр (100%)]
            self.content_splitter.setSizes([0, 1200])
            self.editor.clear() # Очищаем редактор

        # Управление видимостью кнопок
        if self.is_editable:
            # action_edit виден только в режиме просмотра
            if hasattr(self, 'action_edit'):
                self.action_edit.setVisible(not enabled)
            
            # action_save и btn_cancel видны только в режиме редактирования
            if hasattr(self, 'action_save'):
                self.action_save.setVisible(enabled)
            if hasattr(self, 'btn_cancel'):
                self.btn_cancel.setVisible(enabled)
                
            # Сброс состояния изменения при выходе из режима редактирования
            if not enabled and hasattr(self, 'content_changed'):
                self.content_changed = False
                if hasattr(self, 'action_save'):
                    self.action_save.setEnabled(False)


    def setup_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        # Логотип слева
        logo_label = QLabel("  CS2 Guide Hub")
        logo_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #00ff85;")
        logo_label.setContentsMargins(8, 0, 0, 0)
        tb.addWidget(logo_label)

        tb.addSeparator()

        # Кнопки редактирования (только для editor/admin)
        if self.is_editable:
            # 2. Кнопка "Редактировать"
            self.action_edit = QAction(qta.icon("fa5s.edit", color="#00ff85"), "Редактировать", self)
            self.action_edit.triggered.connect(lambda: self.toggle_edit_mode(True))
            tb.addAction(self.action_edit)

            # Кнопка "Сохранить" (Атрибут используется в ContentHandlerMixin)
            self.action_save = QAction(qta.icon("fa5s.save", color="black"), "Сохранить", self)
            self.action_save.setShortcut("Ctrl+S")
            self.action_save.setEnabled(False)
            self.action_save.setVisible(False) 
            self.action_save.triggered.connect(self.save_current_guide) 
            tb.addAction(self.action_save)

            # Кнопка "Отмена" (Атрибут используется в ContentHandlerMixin)
            self.btn_cancel = QPushButton("Отмена")
            self.btn_cancel.setFixedHeight(34)
            self.btn_cancel.setVisible(False)
            # При отмене вызываем cancel_edit, который затем переключает режим обратно
            self.btn_cancel.clicked.connect(lambda: self.cancel_edit(switch_mode=True)) 
            tb.addWidget(self.btn_cancel)

            tb.addSeparator()

        # Админки
        if self.user_role == "admin":
            tb.addAction(qta.icon("fa5s.users-cog", color="#e0e0e0"), "Пользователи", self.show_user_management_dialog)
            tb.addAction(qta.icon("fa5s.sitemap", color="#e0e0e0"), "Структура", self.show_guide_management_dialog)
            tb.addSeparator()

        # Пользователь и выход (справа)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tb.addWidget(spacer)

        self.user_info_label = QLabel()
        self.user_info_label.setStyleSheet("color: #00ff85; font-weight: bold;")
        tb.addWidget(self.user_info_label)

        logout_action = QAction(qta.icon("fa5s.sign-out-alt", color="#ff6b6b"), "Выйти", self)
        logout_action.triggered.connect(self.logout)
        tb.addAction(logout_action)

    # --- Переопределение методов миксина ContentHandlerMixin для управления режимом ---

    def cancel_edit(self, switch_mode: bool = False):
        """Переопределяет метод миксина для добавления переключения режима."""
        # Используем логику из ContentHandlerMixin для сброса текста и статуса
        super().cancel_edit()
        
        # Если отмена прошла успешно (content_changed = False в миксине) и запрошено переключение
        if switch_mode and not self.content_changed:
            self.toggle_edit_mode(False) # Возвращаемся в режим просмотра

    def save_current_guide(self):
        """Переопределяет метод миксина для добавления переключения режима."""
        # Используем логику из ContentHandlerMixin для сохранения
        if super().save_current_guide():
             # Если сохранение прошло успешно
            self.toggle_edit_mode(False) # Возвращаемся в режим просмотра
        # Если сохранение не удалось, режим не переключаем
        
    # --- Методы, которые не требуют изменений в логике переключения режима ---

    def update_user_info_in_toolbar(self):
        role_map = {
                "reader": "Пользователь",
                "admin": "Администратор",
                "editor": "Редактор",
                # Добавьте другие роли по мере необходимости
            }
        role_text = role_map.get(self.user_role, self.user_role.upper())
        self.user_info_label.setText(f"<b>{self.username}</b>ㅤ|ㅤ{role_text}")

    def apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background: #1e1e1e; }
            QToolBar { background: #252525; border-bottom: 1px solid #333; padding: 4px; spacing: 8px; }
            QToolBar::separator { width: 1px; background: #444; margin: 0 8px; }
            QPushButton { background: #333; border: 1px solid #00ff85; color: #e0e0e0; border-radius: 4px; padding: 6px 16px; }
            QPushButton#save_btn { background: #008f4c; color: black; font-weight: bold; }
            QLineEdit { background: #252525; border: 1px solid #444; color: #e0e0e0; padding: 8px; border-radius: 6px; }
            QTreeWidget { background: #252525; border: none; color: #e0e0e0; selection-background-color: #004c26; }
            QTextEdit { background: #252525; border: 1px solid #444; color: #e0e0e0; padding: 8px; border-radius: 6px; }
            QWebEngineView { background: #1e1e1e; }
            QSplitter::handle { background: #333; }
        """)
        if self.is_editable and hasattr(self, 'btn_cancel'):
            self.btn_cancel.setObjectName("save_btn")