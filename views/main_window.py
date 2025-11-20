# views/main_window.py (Обновленный код)

import logging
import markdown
import qtawesome as qta
from typing import TYPE_CHECKING, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QLineEdit,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit, QToolBar,
    QMessageBox, QPushButton, QSizePolicy
)
from PyQt6.QtGui import QAction, QCloseEvent
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtWebEngineWidgets import QWebEngineView

from core.firebase_service import (
    get_structure_metadata,
    # Импорты для firestore, хотя их использование делегируется миксинам
    get_guide_content_firestore_by_structure_id as get_guide_content,
    save_guide_content_firestore_by_structure_id as save_guide_firestore,
    create_new_node, rename_node, delete_node_recursively,
    DEFAULT_GUIDE_CONTENT
)
from views.web_engine import ExternalLinkPage

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

        self.init_tree() # Инициализация переменных для миксинов (включает self.search_timer)
        self.init_content()

        self.action_save = None
        self.action_cancel = None

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

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
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
        # Подключение поиска к self.search_timer
        self.search_input.textChanged.connect(self.search_timer.start)
        sidebar_layout.addWidget(self.search_input)

        # QTreeView теперь инициализируется в TreeHandlerMixin.init_tree()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.clicked.connect(self.on_tree_item_clicked)
        self.tree.doubleClicked.connect(self.on_tree_item_double_clicked)
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

    def closeEvent(self, event: QCloseEvent):
        """
        Перехват события закрытия окна. 
        Делегируем логику обработки несохраненных изменений и остановки слушателей 
        в StatusMixin.
        """
        super().closeEvent(event)


    def toggle_edit_mode(self, enabled: bool):
        """Включает/выключает режим редактирования, контролирует сплиттер и кнопки."""
        self.is_editing_mode = enabled

        # Редактор виден только в режиме редактирования
        self.editor.setVisible(enabled)

        # Управление размерами сплиттера: 50/50 в режиме редактирования, 0/100 в режиме просмотра
        if enabled:
            # При входе в режим редактирования загружаем оригинальный контент
            if self.current_guide_fn:
                # В content_handler.py это сделано в load_guide_by_node_id, 
                # но для переключения режима нужно сделать это здесь, если гайд уже загружен.
                self.editor.setPlainText(self.original_content)
                self.update_webview() # Обновляем просмотр, чтобы видеть контент редактора
            
            # Режим редактирования: [Редактор (50%) | Просмотр (50%)]
            total_width = self.content_splitter.width()
            self.content_splitter.setSizes([total_width // 2, total_width // 2])
        else:
            # Режим просмотра: [Редактор (0) | Просмотр (100%)]
            self.content_splitter.setSizes([0, self.content_splitter.width()])
            self.update_webview() # Обновляем просмотр, чтобы видеть оригинальный контент (если мы вышли без сохранения)


        # Управление видимостью кнопок
        if self.is_editable:
            # action_edit виден только в режиме просмотра
            if hasattr(self, 'action_edit'):
                self.action_edit.setVisible(not enabled)
            
            # action_save и action_cancel видны только в режиме редактирования
            if hasattr(self, 'action_save'):
                self.action_save.setVisible(enabled)
            
            # action_cancel виден только в режиме редактирования
            if hasattr(self, 'action_cancel'):
                # Кнопка "Отмена" видна в режиме редактирования
                # Ее состояние enabled/disabled будет управляться on_content_changed, 
                # но видимость зависит только от режима.
                self.action_cancel.setVisible(enabled)
                
            # Сброс состояния изменения при выходе из режима редактирования
            if not enabled and hasattr(self, 'content_changed'):
                self.content_changed = False
                if hasattr(self, 'action_save'):
                    self.action_save.setEnabled(False)


    def setup_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon) 
        tb.setAllowedAreas(Qt.ToolBarArea.NoToolBarArea)

        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        # 1. Логотип слева
        logo_action = QAction("CS2 Guide Hub", self)
        logo_action.setEnabled(False) # Делаем его некликабельным
        logo_action.setIcon(qta.icon("fa5s.book", color="#00ff85")) 
        logo_action.setIconVisibleInMenu(False) 
        logo_action.setObjectName("action_logo") # Для стилизации
        tb.addAction(logo_action)
        
        tb.addSeparator()

        # 2. Кнопки сохранения и отмены (УДАЛЕНЫ ИЗ ЭТОГО МЕСТА)

        # 3. Админки (слева)
        if self.user_role == "admin":
            admin_icon_color = "#e0e0e0" # Светло-серый
            tb.addAction(qta.icon("fa5s.users-cog", color=admin_icon_color), "Пользователи", self.show_user_management_dialog)
            tb.addAction(qta.icon("fa5s.sitemap", color=admin_icon_color), "Структура", self.show_guide_management_dialog)
            tb.addSeparator()

        # 4. Пользователь и выход (справа)
        # Этот виджет-расширитель выталкивает все, что справа от него, к правому краю.
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tb.addWidget(spacer)
        
        # 🚀 МЕСТО ДЛЯ КНОПОК РЕДАКТИРОВАНИЯ/СОХРАНЕНИЯ/ОТМЕНЫ (СПРАВА)
        if self.is_editable:
            
            # --- Кнопка "СОХРАНИТЬ" (ПЕРЕМЕЩЕНА СЮДА) ---
            self.action_save = QAction(qta.icon("fa5s.save"), "Сохранить", self)
            self.action_save.setObjectName("action_save") # Для стилизации
            self.action_save.setShortcut("Ctrl+S")
            self.action_save.setEnabled(False)
            self.action_save.setVisible(False) 
            self.action_save.triggered.connect(self.save_current_guide) 
            tb.addAction(self.action_save)
            
            # --- Кнопка "ОТМЕНА" (ПЕРЕМЕЩЕНА СЮДА) ---
            self.action_cancel = QAction(qta.icon("fa5s.times"), "Отмена", self)
            self.action_cancel.setObjectName("action_cancel") # Для стилизации
            self.action_cancel.setVisible(False)
            self.action_cancel.triggered.connect(lambda: self.cancel_edit(switch_mode=True)) 
            tb.addAction(self.action_cancel)
            
            # --- Кнопка "РЕДАКТИРОВАТЬ" (ОСТАЕТСЯ ЗДЕСЬ) ---
            self.action_edit = QAction(qta.icon("fa5s.edit"), "Редактировать", self)
            self.action_edit.setObjectName("action_edit") # Для специфической стилизации
            self.action_edit.triggered.connect(lambda: self.toggle_edit_mode(True))
            tb.addAction(self.action_edit)
            
            tb.addSeparator() # Добавляем разделитель перед информацией о пользователе


        self.user_info_label = QLabel()
        self.user_info_label.setStyleSheet("color: #00ff85; font-weight: bold;")
        tb.addWidget(self.user_info_label)

        # Кнопка "Выйти"
        logout_action = QAction(qta.icon("fa5s.sign-out-alt", color="#ff6b6b"), "Выйти", self)
        logout_action.triggered.connect(self.logout)
        tb.addAction(logout_action)

    def cancel_edit(self, switch_mode: bool = False):
        """Переопределяет метод миксина для добавления переключения режима."""
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
            return True
        return False
        

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
        # Обновленный стили: более темный фон, сглаженные углы, мягкие цвета акцента.
        
        base_style = """
            /* ==================== BASE STYLES ==================== */
            QMainWindow { background: #121212; }
            QToolBar { 
                background: #1e1e1e; 
                border-bottom: 1px solid #2d2d2d; 
                padding: 4px; 
                spacing: 4px; 
            }
            QToolBar::separator { 
                width: 1px; 
                background: #333; 
                margin: 0 8px; 
            }
            
            QToolButton { 
                background: transparent;
                border: none;
                padding: 6px 10px;
                margin: 2px;
                border-radius: 6px;
                color: #e0e0e0; /* Основной цвет текста для обычных кнопок */
                font-weight: 500;
            }
            QToolButton:hover { 
                background: #2d2d2d; /* Темно-серый при наведении */
            }
            QToolButton:pressed {
                background: #3c3c3c;
            }
            
            /* Логотип */
            QToolAction#action_logo QToolButton {
                QToolButton::menu-indicator { image: none; width: 0px; } 
                font-weight: bold; 
                font-size: 16px; 
                color: #00ff85;
                padding-left: 8px;
                background: transparent;
            }
            QToolAction#action_logo QToolButton:hover {
                background: transparent;
            }


            /* ==================== АКЦЕНТНЫЕ КНОПКИ ==================== */
            
            /* Кнопка РЕДАКТИРОВАТЬ */
            QAction#action_edit QToolButton {
                background: #008f4c; /* Темный зеленый фон */
                border-radius: 6px;
                color: #1e1e1e; /* Темный текст на зеленом */
                font-weight: bold;
                padding: 6px 16px;
            }
            QAction#action_edit QToolButton:hover {
                background: #00b35c; /* Более светлый зеленый при наведении */
            }
            QAction#action_edit QToolButton:pressed {
                background: #00703a;
            }
            
            /* Кнопка СОХРАНИТЬ */
            QAction#action_save QToolButton {
                background: #00ff85; /* Яркий зеленый фон */
                border-radius: 6px;
                color: #1e1e1e; /* Темный текст на ярком зеленом */
                font-weight: bold;
                padding: 6px 16px;
            }
            QAction#action_save QToolButton:hover {
                background: #33ff9e;
            }
            QAction#action_save QToolButton:pressed {
                background: #00c66a;
            }
            QAction#action_save QToolButton:disabled {
                background: #3c3c3c; /* Отключенный серый фон */
                color: #777;
            }

            /* Кнопка ОТМЕНА (Теперь QAction) */
            QAction#action_cancel QToolButton { 
                background: transparent; 
                border: 1px solid #ff6b6b; 
                color: #ff6b6b; 
                border-radius: 6px; 
                padding: 6px 16px; 
                margin: 2px;
            }
            QAction#action_cancel QToolButton:hover {
                background: #402323; /* Темно-красный фон при наведении */
                color: #ffe0e0;
            }
            QAction#action_cancel QToolButton:pressed {
                background: #5a3131;
            }


            /* ==================== INPUTS & CONTENT ==================== */
            
            QLineEdit { 
                background: #1e1e1e; 
                border: 1px solid #333; 
                color: #e0e0e0; 
                padding: 8px; 
                border-radius: 8px; 
                font-size: 14px;
            }
            
            QTextEdit { 
                background: #1e1e1e; 
                border: 1px solid #2d2d2d; 
                color: #e0e0e0; 
                padding: 10px; 
                border-radius: 8px; 
                line-height: 1.5;
            }
            
            QTreeWidget, QTreeView { 
                background: #121212; 
                border: none; 
                color: #e0e0e0;
                show-decoration-selected: 0; 
                outline: none; 
            }
            
            QTreeWidget::item, QTreeView::item {
                padding: 6px 4px; 
                margin: 2px 0;
                border-radius: 4px;
                border: none; 
            }
            
            QTreeWidget::item:hover, QTreeView::item:hover {
                background: #1e1e1e;
                color: #00ff85;
            }

            QTreeWidget::item:selected, QTreeView::item:selected {
                background: #1e1e1e; 
                color: #00ff85; 
                border: none;
                outline: none; 
            }
            
            QWebEngineView { 
                background: #121212; 
                border: none;
            }
            
            /* Разделитель сплиттера */
            QSplitter::handle { 
                background: #2d2d2d; 
                width: 2px;
                height: 2px;
            }
            QSplitter::handle:hover {
                 background: #00ff85; 
            }
        """
        self.setStyleSheet(base_style)