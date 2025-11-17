# views/main_window.py
import logging
import markdown
import qtawesome as qta
from typing import TYPE_CHECKING
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QSplitter, QTreeWidget,
    QTreeWidgetItem, QTextEdit, QToolBar, QDialog, QFileDialog,
    QTableWidget, QTableWidgetItem, QComboBox, QMessageBox, QFormLayout, 
    QInputDialog, QToolButton, QMenu, QSizePolicy, QApplication, QStackedWidget
)
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal, QObject, QSize 
from PyQt6.QtGui import QFont, QIcon, QAction, QDesktopServices 
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage 

# Импорты из core
from core.firebase_service import (
    get_all_guides_for_search_new, 
    get_structure_metadata,       
    get_guide_content_firestore_by_structure_id as get_guide_content, 
    save_guide_content_by_structure_id as save_guide_firestore,      
    create_new_node,              
    rename_node,                   
    delete_node_recursively       
)
from views.web_engine import ExternalLinkPage
from views.admin_dialogs import UserManagementDialog, GuideManagementDialog

# ИСПРАВЛЕНИЕ ОШИБКИ: Круговой импорт
if TYPE_CHECKING:
    from views.auth_dialogs import LoginDialog

class MainWindow(QMainWindow):
    # 🔥 ИСПРАВЛЕНИЕ КОНСТРУКТОРА: Принимаем username, затем user_role, как передано в main.py
    def __init__(self, username: str, user_role: str, parent: 'LoginDialog' = None):
        super().__init__()
        self.parent_dialog = parent
        self.username = username
        self.user_role = user_role # 🔥 Теперь user_role получает ПРАВИЛЬНОЕ значение роли
        self.current_guide_fn = None  
        self.original_content = ""
        self.content_changed = False
        self.search_cache = {}
        self.guide_map = {} 
        # КЛЮЧЕВОЙ ФЛАГ: Определяет права доступа
        self.is_editable = self.user_role in ('editor', 'admin') 
        self.current_node_type = None
        
        # 🔥 НОВОЕ: Для синхронизации и восстановления позиции прокрутки
        self._pending_scroll_pos = 0 # Позиция прокрутки, которую нужно восстановить после обновления HTML
        self.is_syncing = False     # Флаг для предотвращения бесконечного цикла прокрутки
        
        # Добавляем атрибуты для кнопок, чтобы избежать ошибок AttributeError, даже если они не будут созданы
        self.save_btn = None
        self.btn_cancel = None
        self.action_save = None
        self.btn_view = None
        self.btn_edit = None
        self.separator_frame_mode = None

        self.setup_ui()
        self.setup_toolbar() 
        self.apply_style()
        self.setup_timers()
        
        # Загрузка древа при инициализации
        self.populate_tree() 
        self.load_guide_by_node_id("root_info") # Загружаем приветственный гайд
        
        if self.user_role == 'reader':
            self.set_status_ok(f"Успешный вход. Роль: ЧИТАТЕЛЬ", 5000)
        else:
            self.set_status_ok(f"Успешный вход. Роль: {self.user_role.upper()}", 5000)

    def setup_ui(self):
        self.setWindowTitle("CS2 Guide Hub")
        self.setMinimumSize(1200, 800)

        # Центральный виджет и главный макет
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setCentralWidget(central_widget)
        
        # Строка статуса
        self.status_bar_label = QLabel("Готов.")
        self.statusBar().addWidget(self.status_bar_label)
        
        # --- Сплиттер для боковой панели и основного контента ---
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setFrameShape(QFrame.Shape.NoFrame)
        
        # 1. Боковая панель (Навигация/Древо)
        sidebar = self._create_sidebar()
        self.splitter.addWidget(sidebar)

        # 2. Основной контент (Просмотр и Редактирование)
        self.content_area = self._create_content_area()
        self.splitter.addWidget(self.content_area)
        
        self.splitter.setSizes([250, 950]) 
        main_layout.addWidget(self.splitter)

    # ==================== МЕТОДЫ СОЗДАНИЯ ВИДЖЕТОВ ====================

    def _create_sidebar(self):
        """Создает боковую панель (БЛОК 1)."""
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(10)
        
        # Поиск
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Поиск по гайдам...")
        self.search_input.textChanged.connect(self.search_guides)
        sidebar_layout.addWidget(self.search_input)

        # Древовидный виджет
        self.tree = QTreeWidget()
        self.tree.setObjectName("treeWidget")
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)
        self.tree.itemDoubleClicked.connect(self.on_tree_item_double_clicked)
        # Если пользователь не редактор, запрещаем прямое редактирование названий
        if not self.is_editable:
            self.tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers) 
        else:
            self.tree.setEditTriggers(QTreeWidget.EditTrigger.DoubleClicked | QTreeWidget.EditTrigger.EditKeyPressed) 
            
        sidebar_layout.addWidget(self.tree)
        
        return sidebar

    def _create_content_area(self):
        """Создает основную рабочую область (БЛОК 3)."""
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 1. Виджеты контента, создаются только ОДИН РАЗ
        self.editor = QTextEdit()
        self.editor.setObjectName("textEditor")
        # 🔥 НОВОЕ: Подключение сигнала прокрутки для синхронизации
        self.editor.verticalScrollBar().valueChanged.connect(self.synchronize_scroll) 
        # ... (настройка self.editor) ...
        self.editor.textChanged.connect(self.on_content_changed)
        
        self.webview = QWebEngineView()
        self.webview.setObjectName("webView")
        # ... (настройка self.webview) ...

        # 2. РЕЖИМ РЕДАКТИРОВАНИЯ: Разделитель (Splitter)
        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_splitter.addWidget(self.editor)
        # 🔥 ВАЖНО: self.webview будет добавлен сюда динамически в switch_to_edit

        # 3. РЕЖИМ ПРОСМОТРА: Контейнер для webview в режиме просмотра
        self.view_container = QWidget()
        self.view_layout = QVBoxLayout(self.view_container)
        self.view_layout.setContentsMargins(0, 0, 0, 0)
        # 🔥 Начальное положение self.webview - внутри view_container
        self.view_layout.addWidget(self.webview) 
        
        # 4. ГЛАВНЫЙ КОНТЕЙНЕР: QStackedWidget
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.view_container)    # Index 0: Просмотр (только Webview)
        self.stacked_widget.addWidget(self.editor_splitter) # Index 1: Редактирование (Editor + Webview в сплиттере)
        
        content_layout.addWidget(self.stacked_widget)
        
        # По умолчанию мы уже в режиме просмотра (Index 0)
        
        return content_widget

    def _create_save_button_action(self, toolbar):
        """Создает и добавляет действие 'Сохранить' в ToolBar."""
        self.action_save = QAction(qta.icon("fa5s.save", color="black"), "Сохранить (Ctrl+S)", self)
        self.action_save.setObjectName("save_action")
        self.action_save.setToolTip("Сохранить изменения в облаке")
        self.action_save.setShortcut("Ctrl+S")
        self.action_save.triggered.connect(self.save_current_guide)
        self.action_save.setEnabled(False)
        
        # Создаем ToolButton для кастомной стилизации
        self.save_btn = QToolButton(toolbar)
        self.save_btn.setDefaultAction(self.action_save)
        self.save_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.save_btn.setObjectName("save_action_button") 
        toolbar.addWidget(self.save_btn)
        
    def _create_cancel_button_action(self, toolbar):
        """Создает и добавляет действие 'Отмена' в ToolBar."""
        self.action_cancel = QAction(qta.icon("fa5s.times", color="#ff6b6b"), "Отмена", self)
        self.action_cancel.setObjectName("cancel_action")
        self.action_cancel.setToolTip("Отменить несохраненные изменения")
        self.action_cancel.triggered.connect(self.cancel_edit)
        
        self.btn_cancel = QToolButton(toolbar)
        self.btn_cancel.setDefaultAction(self.action_cancel)
        self.btn_cancel.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_cancel.hide()
        toolbar.addWidget(self.btn_cancel)

    def _create_mode_button(self, icon_name: str, text: str, checked: bool, callback, enabled: bool = True) -> QToolButton:
        """Создает и возвращает настраиваемую кнопку переключения режима."""
        btn = QToolButton(self)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setText(text)
        btn.setIcon(qta.icon(f"fa5s.{icon_name}", color="#e0e0e0")) 
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setEnabled(enabled)
        btn.clicked.connect(callback)
        return btn


    def apply_style(self):
        # --- Стили Dark Modern (обновленные) ---
        style = """
        /* Общие стили и фоны */
        QMainWindow { background-color: #1a1a1a; }
        
        /* --- ToolBar (Объединенная панель управления) --- */
        QToolBar { 
            background-color: #232323; 
            border: none; 
            padding: 5px; 
            border-bottom: 2px solid #00ff85; /* Более заметный разделитель */
        } 
        QToolBar::separator { background: #333333; width: 1px; margin: 5px 5px; } 

        /* Стилизация виджета с названием/логотипом внутри ToolBar */
        QWidget#titleLogoWidget {
            margin-right: 15px; /* Отделяем лого/заголовок от кнопок */
        }
        QLabel#appTitleLabel {
            color: #00ff85; 
            font-size: 18px; /* Уменьшаем размер для ToolBar */
            font-weight: bold;
            text-transform: uppercase;
        }
        
        /* Стилизация хлебных крошек */
        QLabel#breadcrumbLabel {
            color: #e0e0e0;
            font-size: 14px;
            font-weight: 500;
            margin-left: 10px;
        }

        /* --- Кнопки Save/Cancel в ToolBar (QToolButton) --- */
        QToolButton {
            background-color: #333333; 
            border: 1px solid #4a4a4a;
            padding: 6px 12px;
            color: #e0e0e0;
            border-radius: 4px;
            margin-right: 5px; /* Разделяем кнопки */
        }
        QToolButton:hover {
            background-color: #4a4a4a;
            border-color: #00ff85;
        }
        
        /* Кнопка Сохранить */
        QToolButton[objectName="save_action_button"] { /* Используем objectName кнопки */
            background-color: #008f4c;
            border: 1px solid #00ff85;
            color: black;
            font-weight: bold;
        }
        QToolButton[objectName="save_action_button"]:hover {
            background-color: #00ff85;
        }
        QToolButton[objectName="save_action_button"]:disabled {
             background-color: #3a3a3a;
             border-color: #4a4a4a;
             color: #999999;
        }
        
        /* Кнопки переключения режима (Просмотр/Редактирование) */
        QToolButton[checkable=true] {
            border: none;
            background-color: transparent;
            color: #e0e0e0;
            font-weight: 500;
        }
        QToolButton[checkable=true]:hover {
            background-color: #333333;
        }
        QToolButton[checkable=true]:checked {
            border-bottom: 3px solid #00ff85;
            background-color: #2a2a2a;
            color: #00ff85;
            font-weight: bold;
        }

        /* --- БЛОК 1: Боковая панель (Sidebar) --- */
        QWidget#sidebar { 
            background-color: #232323; 
            border-right: 1px solid #333333;
        }
        
        /* Древовидный виджет */
        QTreeWidget {
            background-color: #232323;
            border: none;
            padding: 0px;
            font-size: 14px;
        }
        QTreeWidget::item {
            padding: 7px 0; 
        }
        QTreeWidget::item:selected {
            background-color: #00ff85;
            color: black;
            border-radius: 0px; 
        }
        
        /* Поиск */
        QLineEdit#searchInput {
            background-color: #1a1a1a;
            border: 1px solid #00ff85; 
            padding: 10px 10px;
            border-radius: 6px;
            font-size: 14px;
        }

        /* --- БЛОК 3: Основной контент --- */
        
        QTextEdit#textEditor {
            background-color: #1a1a1a;
            border: none;
            padding: 20px; 
            border-right: 1px solid #333333; 
        }
        
        /* Сплиттер (общий) */
        QSplitter::handle {
            background-color: #333333;
            width: 3px;
            height: 3px;
        }
        QSplitter::handle:hover {
            background-color: #00ff85;
        }
        
        /* Строка состояния */
        QStatusBar {
            background-color: #000000; 
            border-top: 1px solid #333333;
        }
        
        /* Меню и Скроллбары - стили оставлены без изменений */
        QMenu {
            background: #2a2a2a; 
            border: 1px solid #00ff85; 
            color: #e0e0e0;
            border-radius: 4px;
        }
        QMenu::item { 
            padding: 6px 15px 6px 10px; 
        }
        QMenu::item:selected { 
            background: #00ff85; 
            color: black; 
            border-radius: 2px; 
        }
        QScrollBar:vertical, QScrollBar:horizontal {
            border: none;
            background: #2a2a2a;
            width: 8px;
            height: 8px;
            margin: 0px 0px 0px 0px;
        }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background: #4a4a4a;
            min-height: 20px;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
            background: #00ff85;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, 
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            border: none;
            background: none;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
            background: none;
        }
        """
        self.setStyleSheet(style)
        
    def setup_toolbar(self):
        """
        Создает объединенный ToolBar. 
        🔥 ИСПРАВЛЕНИЕ: Кнопки сохранения, редактирования и просмотра 
        добавляются ТОЛЬКО, если self.is_editable = True.
        """
        toolbar = QToolBar("Основная панель")
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        
        # 1. Логотип и Название приложения (Всегда)
        title_widget = QWidget()
        title_widget.setObjectName("titleLogoWidget")
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        logo_label = QLabel()
        logo_label.setPixmap(qta.icon("fa5s.cogs", color="#00ff85").pixmap(QSize(20, 20)))
        
        title_label = QLabel("CS2 GUIDE HUB")
        title_label.setObjectName("appTitleLabel")
        
        title_layout.addWidget(logo_label)
        title_layout.addWidget(title_label)
        toolbar.addWidget(title_widget)
        toolbar.addSeparator()

        # 2. Хлебные крошки (Title) (Всегда)
        self.breadcrumb_label = QLabel(" / Добро пожаловать!")
        self.breadcrumb_label.setObjectName("breadcrumbLabel")
        toolbar.addWidget(self.breadcrumb_label)
        
        # 3. Кнопки Администрирования (Только для admin)
        if self.user_role == 'admin':
            action_user_management = QAction(qta.icon("fa5s.users-cog", color="#ffcc66"), "Упр. пользователями", self)
            action_user_management.triggered.connect(self.show_user_management_dialog)
            
            action_guide_management = QAction(qta.icon("fa5s.sitemap", color="#ffcc66"), "Упр. структурой", self)
            action_guide_management.triggered.connect(self.show_guide_management_dialog)
            
            toolbar.addAction(action_user_management)
            toolbar.addAction(action_guide_management)
            toolbar.addSeparator()

        # 4. Растягивающийся разделитель (Всегда)
        spacer = QWidget() 
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        
        # 5. КОНТРОЛЫ РЕДАКТИРОВАНИЯ И ПРОСМОТРА (Только для editor/admin)
        if self.is_editable:
            # 5.1 Кнопки Сохранения/Отмены
            self._create_cancel_button_action(toolbar) 
            self._create_save_button_action(toolbar)
            
            # 5.2 Разделитель между действиями и режимами
            self.separator_frame_mode = QFrame()
            self.separator_frame_mode.setFrameShape(QFrame.Shape.VLine)
            self.separator_frame_mode.setFrameShadow(QFrame.Shadow.Sunken)
            self.separator_frame_mode.setStyleSheet("QFrame {color: #4a4a4a; margin: 5px 0;}")
            toolbar.addWidget(self.separator_frame_mode)
            
            # 5.3 Переключатели Режима
            self.btn_view = self._create_mode_button("eye", "Просмотр", True, self.switch_to_view)
            self.btn_edit = self._create_mode_button("pen", "Редактировать", False, self.switch_to_edit, enabled=self.is_editable)
            
            toolbar.addWidget(self.btn_view)
            toolbar.addWidget(self.btn_edit)
        # else: Если is_editable=False (reader), этот блок пропускается, и кнопки не добавляются.
        
        # 6. Сменить пользователя (Всегда)
        toolbar.addSeparator()
        action_logout = QAction(qta.icon("fa5s.sign-out-alt", color="#ff6b6b"), "Выход", self)
        action_logout.triggered.connect(self.logout)
        toolbar.addAction(action_logout)

    # ==================== ОСТАЛЬНЫЕ МЕТОДЫ ====================
    
    def setup_timers(self):
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.update_webview)
        
    # 🔥 НОВЫЙ ВСПОМОГАТЕЛЬНЫЙ МЕТОД: Создает окно с русскими кнопками
    def _create_save_warning_box(self, title: str, text: str):
        """Создает QMessageBox с русскими кнопками Сохранить, Не сохранять, Отмена."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        msg_box.setIcon(QMessageBox.Icon.Warning)

        # Создаем кнопки с русским текстом и связываем их с ролями
        save_btn = msg_box.addButton("Сохранить", QMessageBox.ButtonRole.YesRole)
        discard_btn = msg_box.addButton("Не сохранять", QMessageBox.ButtonRole.NoRole)
        cancel_btn = msg_box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.setDefaultButton(save_btn)
        return msg_box, save_btn, discard_btn, cancel_btn


    def _prompt_save_changes_dialog(self) -> bool:
        """
        Проверяет наличие несохраненных изменений и предлагает их сохранить/отменить.
        Возвращает True, если можно продолжить (сохранено/отменено/нет изменений).
        Возвращает False, если пользователь выбрал "Отмена" и нужно прервать действие.
        """
        if not self.content_changed or not self.is_editable:
            return True # Нет изменений или нет прав, можно продолжать

        title_for_messages = self.breadcrumb_label.text().replace(" / ", "")
        
        # 🔥 ИСПРАВЛЕНИЕ: Используем русские кнопки
        msg_box, save_btn, discard_btn, cancel_btn = self._create_save_warning_box(
            "Несохраненные изменения",
            f"Сохранить изменения в '{title_for_messages}' перед переходом?"
        )
        
        msg_box.exec()
        clicked_button = msg_box.clickedButton()

        if clicked_button == cancel_btn:
            return False # Прервать действие

        if clicked_button == save_btn:
            self.save_current_guide()
            # Если после попытки сохранения content_changed все еще True (например, ошибка сети), 
            # тоже прерываем, чтобы не потерять данные
            if self.content_changed: 
                return False 
                
        elif clicked_button == discard_btn:
            self.cancel_edit()
            
        return True

    def load_guide_by_node_id(self, node_id: str):
        """Загружает контент гайда по ID узла структуры."""
        item = self.guide_map.get(node_id)
        
        if not item or item.data(0, Qt.ItemDataRole.WhatsThisRole) != 'guide':
            if node_id == "root_info": pass 
            else: 
                # Если это не гайд, убедимся, что интерфейс в режиме просмотра
                if self.is_editable: self.switch_to_view() 
                return

        title_for_messages = item.text(0) if item else "Загрузка..."
        
        # Проверка на несохраненные изменения (только для редакторов)
        if not self._prompt_save_changes_dialog():
             return

        # 🔥 ИСПРАВЛЕНИЕ: Принудительно устанавливаем read-only/editable при загрузке
        if not self.is_editable:
            self.editor.setReadOnly(True)
        else:
            self.editor.setReadOnly(False)
            
        guide_data = get_guide_content(node_id)
        
        if not guide_data:
            self.editor.setPlainText(f"# Ошибка\n\nКонтент для гайда ID: {node_id} не найден. Это может быть ошибка базы данных.")
            self.editor.setReadOnly(True) 
            self.current_guide_fn = None
            self.original_content = ""
            self.content_changed = False
            # Проверка, что кнопки существуют, прежде чем их отключать/скрывать
            if self.action_save: self.action_save.setEnabled(False)
            if self.btn_cancel: self.btn_cancel.hide()
            self.update_webview()
            return

        md_content = guide_data.get('content', '')
        self.current_guide_fn = node_id
        self.current_node_type = 'guide'
        self.original_content = md_content
        self.content_changed = False
        
        if self.action_save: self.action_save.setEnabled(False)
        if self.btn_cancel: self.btn_cancel.hide()
        
        self.editor.setPlainText(md_content)
        self.setWindowTitle(f"CS2 Guide Hub - {title_for_messages}")
        self.breadcrumb_label.setText(f" / {title_for_messages}")
        
        self.timer.start(50) # Запуск таймера для обновления webview

    def on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Обработка клика по элементу дерева."""
        node_type = item.data(0, Qt.ItemDataRole.WhatsThisRole)
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        
        if node_type == 'guide':
            self.load_guide_by_node_id(node_id)
        elif node_type == 'folder':
            item.setExpanded(not item.isExpanded())

    def on_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Обработка двойного клика (для переименования, если разрешено)."""
        node_type = item.data(0, Qt.ItemDataRole.WhatsThisRole)
        # Если пользователь имеет право на редактирование и это не папка
        if self.is_editable and node_type != 'folder':
            if item.flags() & Qt.ItemFlag.ItemIsEditable:
                self.tree.editItem(item, column)


    def show_context_menu(self, position):
        """Отображает контекстное меню для дерева."""
        item = self.tree.itemAt(position)
        menu = QMenu(self)
        
        action_new_guide = QAction(qta.icon("fa5s.file-alt", color="#00ff85"), "Создать новый гайд", self)
        action_new_guide.triggered.connect(lambda: self.create_new_node_dialog('guide', item))
        
        action_new_folder = QAction(qta.icon("fa5s.folder-plus", color="#ffcc66"), "Создать новую папку", self)
        action_new_folder.triggered.connect(lambda: self.create_new_node_dialog('folder', item))

        # 🔥 ИСПРАВЛЕНИЕ: Проверка прав доступа для всех действий управления структурой
        if self.is_editable:
            menu.addAction(action_new_folder)
            menu.addAction(action_new_guide)
            
            if item:
                node_type = item.data(0, Qt.ItemDataRole.WhatsThisRole)
                node_name = item.text(0)
                node_id = item.data(0, Qt.ItemDataRole.UserRole)
                
                if node_id and node_id not in ['root_info', 'folder_maps', 'root_settings']:
                    menu.addSeparator()
                    
                    action_rename = QAction(qta.icon("fa5s.edit", color="#e0e0e0"), "Переименовать", self)
                    action_rename.triggered.connect(lambda: self.rename_node_dialog(node_id, node_name))
                    menu.addAction(action_rename)
                    
                    action_delete = QAction(qta.icon("fa5s.trash-alt", color="#ff6b6b"), "Удалить узел", self)
                    action_delete.triggered.connect(lambda: self.delete_node_dialog(node_id, node_name))
                    menu.addAction(action_delete)

        if menu.actions():
            menu.exec(self.tree.viewport().mapToGlobal(position))

    def create_new_node_dialog(self, node_type: str, selected_item: QTreeWidgetItem | None):
        """Создает новый узел (папку или гайд)."""
        
        parent_id = selected_item.data(0, Qt.ItemDataRole.UserRole) if selected_item else None
        parent_type = selected_item.data(0, Qt.ItemDataRole.WhatsThisRole) if selected_item else None
        
        # Новый узел не может быть создан внутри гайда, только в папке или на корневом уровне
        if parent_type == 'guide':
            QMessageBox.warning(self, "Ошибка создания", "Нельзя создать узел внутри гайда. Выберите папку или корневой уровень.")
            return

        name_type = "папку" if node_type == 'folder' else "гайд"
        text, ok = QInputDialog.getText(self, f"Создать {name_type}", f"Введите название для новой {name_type}.")
        if not ok or not text.strip():
            return
            
        new_name = text.strip()
        
        if node_type == 'guide':
            # Для нового гайда используем стандартный шаблон контента
            new_node_id = create_new_node(new_name, parent_id, node_type)
        else:
            new_node_id = create_new_node(new_name, parent_id, node_type, guide_content=None)
            
        if new_node_id:
            self.set_status_ok(f"{name_type.capitalize()} '{new_name}' успешно создан.", 5000)
            self.repopulate_tree()
            if node_type == 'guide':
                self.load_guide_by_node_id(new_node_id)
        else:
            self.set_status_error(f"Ошибка при создании {name_type} в Firebase.", 5000)

    def rename_node_dialog(self, node_id: str, old_name: str):
        """Общий диалог переименования узла."""
        if node_id in ['root_info', 'folder_maps', 'root_settings']:
            QMessageBox.warning(self, "Ошибка", "Нельзя переименовать базовый системный узел.")
            return

        new_name, ok = QInputDialog.getText(self, "Переименовать", "Введите новое название:", text=old_name)
        if ok and new_name.strip() and new_name != old_name:
            new_name = new_name.strip()
            if rename_node(node_id, new_name):
                self.set_status_ok(f"Узел '{old_name}' переименован в '{new_name}'.", 5000)
                self.repopulate_tree()
                if self.current_guide_fn == node_id:
                    self.breadcrumb_label.setText(f" / {new_name}")
                    self.setWindowTitle(f"CS2 Guide Hub - {new_name}")
            else:
                self.set_status_error("Не удалось переименовать узел.", 5000)

    def delete_node_dialog(self, node_id: str, node_name: str) -> bool:
        """Общий диалог рекурсивного удаления узла."""
        reply = QMessageBox.question(
            self, "Подтверждение удаления", 
            f"Вы уверены, что хотите навсегда удалить '{node_name}'?\n\n"
            "**ВНИМАНИЕ: Если это папка, будет удалено ВСЕ ее содержимое и соответствующий контент!**",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if delete_node_recursively(node_id):
                self.set_status_ok(f"Узел '{node_name}' успешно удален из облака.", 5000)
                self.repopulate_tree()
                if self.current_guide_fn == node_id:
                    self.current_guide_fn = None
                    self.load_guide_by_node_id("root_info") # Переходим на приветственный гайд
                return True
            else:
                self.set_status_error("Не удалось удалить узел.", 5000)
                return False
        return False
        
    def repopulate_tree(self):
        """Очищает кэш поиска и перестраивает дерево."""
        self.search_cache = {}
        self.populate_tree()

    def populate_tree(self, filter_results: set[str] | None = None):
        """Строит дерево QTreeWidget из плоского списка узлов структуры."""
        self.tree.clear()
        self.guide_map = {}
        all_nodes = get_structure_metadata()
        if not all_nodes:
            self.set_status_error("Не удалось загрузить структуру гайдов из облака. Проверьте подключение.", 0)
            return

        children_map = {}
        for node in all_nodes:
            parent_id = node.get('parent_id')
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(node)

        def build_tree_recursive(parent_id: str | None, qt_parent_item: QTreeWidgetItem):
            children = children_map.get(parent_id, [])
            for node in children:
                node_id = node['id']
                node_name = node['name']
                node_type = node['type']
                qt_item = QTreeWidgetItem([node_name])
                qt_item.setData(0, Qt.ItemDataRole.UserRole, node_id)
                qt_item.setData(0, Qt.ItemDataRole.WhatsThisRole, node_type)
                
                # Настройка иконки и рекурсивный вызов
                if node_type == 'folder':
                    qt_item.setIcon(0, qta.icon("fa5s.folder", color="#ffcc66"))
                    build_tree_recursive(node_id, qt_item)
                    # Фильтрация: если папка не содержит результатов поиска, пропускаем ее (кроме корневых)
                    if filter_results is not None and qt_item.childCount() == 0 and parent_id is not None: 
                        continue
                
                elif node_type == 'guide':
                    # Фильтрация: если это гайд, и он не в результатах поиска, пропускаем
                    if filter_results is not None and node_id not in filter_results: 
                        continue
                    qt_item.setIcon(0, qta.icon("fa5s.file-alt", color="#e0e0e0"))
                    self.guide_map[node_id] = qt_item

                # Разрешаем редактирование названий только для редакторов/админов
                if self.is_editable:
                    qt_item.setFlags(qt_item.flags() | Qt.ItemFlag.ItemIsEditable)

                qt_parent_item.addChild(qt_item)

        build_tree_recursive(None, self.tree.invisibleRootItem())
        
        # Расширяем дерево: полностью, если нет фильтра, или только те, что имеют результаты
        if filter_results is None:
            self.tree.expandAll()
        else:
            self.tree.expandAll() 
            
        self.set_status_ok("Структура гайдов загружена.", 2000)

    def search_guides(self, query):
        """Поиск по контенту, возвращает ID узлов структуры."""
        if not query:
            self.populate_tree()
            return
            
        query = query.lower().strip()
        found_ids = set()

        if not self.search_cache:
            self.search_cache = get_all_guides_for_search_new()

        for node_id, data in self.search_cache.items():
            title = data.get('title', '').lower()
            content = data.get('content', '').lower()
            if query in title or query in content:
                found_ids.add(node_id)

        self.populate_tree(filter_results=found_ids)

    def switch_to_edit(self):
        """Переключает режим на Редактирование (две панели)."""
        if not self.is_editable:
            return

        # 1. Перемещение Webview обратно в сплиттер
        if self.webview.parent() == self.view_container:
            # Удаляем из контейнера просмотра
            self.view_layout.removeWidget(self.webview)
            # Вставляем его во вторую позицию сплиттера (после self.editor)
            self.editor_splitter.insertWidget(1, self.webview)
            # Устанавливаем 50/50
            self.editor_splitter.setSizes([self.editor_splitter.width() // 2, self.editor_splitter.width() // 2])

        # 2. Переключаемся на индекс 1
        self.stacked_widget.setCurrentIndex(1)

        # 3. Управление кнопками
        if self.btn_edit: self.btn_edit.setChecked(True)
        if self.btn_view: self.btn_view.setChecked(False)

    def switch_to_view(self):
        """Переключает режим на Просмотр."""
        
        # 🔥 НОВАЯ ПРОВЕРКА: Если есть несохраненные изменения, спрашиваем пользователя
        if not self._prompt_save_changes_dialog():
            # Если пользователь нажал "Отмена", возвращаем кнопку "Редактировать" в активное состояние
            if self.is_editable and self.btn_edit:
                 self.btn_edit.setChecked(True)
                 self.btn_view.setChecked(False)
            return

        # 1. Перемещение Webview в контейнер просмотра (если оно было в сплиттере)
        if self.webview.parent() == self.editor_splitter:
             # Добавление в self.view_layout автоматически удаляет виджет из QSplitter
             self.view_layout.addWidget(self.webview) 

        # 2. Переключаемся на индекс 0
        self.stacked_widget.setCurrentIndex(0)
        
        # 3. Управление кнопками
        if self.is_editable and self.btn_view and self.btn_edit:
            self.btn_view.setChecked(True)
            self.btn_edit.setChecked(False)
            
    # ==================== СИНХРОНИЗАЦИЯ ПРОКРУТКИ И ОБНОВЛЕНИЕ ПРЕВЬЮ ====================
            
    def synchronize_scroll(self, value):
        """🔥 НОВОЕ: Синхронизирует прокрутку редактора с превью-панелью."""
        # Предотвращение бесконечного цикла, если прокрутка была вызвана из кода
        # и выход, если мы не в режиме редактирования
        if self.is_syncing or self.stacked_widget.currentIndex() != 1:
            return

        self.is_syncing = True
        
        # 1. Получаем данные прокрутки редактора
        scroll_bar = self.editor.verticalScrollBar()
        max_value = scroll_bar.maximum()
        min_value = scroll_bar.minimum()
        
        # Избегаем деления на ноль
        if max_value - min_value == 0:
            self.is_syncing = False
            return
            
        # 2. Рассчитываем процент прокрутки
        scroll_ratio = (value - min_value) / (max_value - min_value)
        
        # 3. Применяем прокрутку к QWebEngineView через JavaScript
        # Вычисляем максимальную прокрутку (полная высота - высота окна) и применяем коэффициент
        js_code = f"""
        var docHeight = Math.max(
            document.body.scrollHeight, document.documentElement.scrollHeight,
            document.body.offsetHeight, document.documentElement.offsetHeight,
            document.body.clientHeight, document.documentElement.clientHeight
        );
        var viewHeight = window.innerHeight;
        var maxScroll = docHeight - viewHeight;
        var newScroll = maxScroll * {scroll_ratio:.4f};
        window.scrollTo(0, newScroll);
        """
        self.webview.page().runJavaScript(js_code)
        
        self.is_syncing = False
    
    def _restore_scroll_on_load(self, ok):
        """🔥 НОВОЕ: Callback после загрузки страницы для восстановления позиции прокрутки."""
        if self.is_syncing:
            return # Не вмешиваемся, если идет синхронизация
        
        if self._pending_scroll_pos > 0:
            self.is_syncing = True # Включаем, чтобы сброс прокрутки не вызывал синхронизацию редактора
            
            # Устанавливаем позицию прокрутки с помощью JavaScript
            js_code = f"window.scrollTo(0, {self._pending_scroll_pos});"
            self.webview.page().runJavaScript(js_code)
            self._pending_scroll_pos = 0 # Сброс
            
            self.is_syncing = False
            
        # Отключение сигнала после использования
        try:
            self.webview.loadFinished.disconnect(self._restore_scroll_on_load)
        except TypeError:
            pass # Already disconnected or not connected

    def _update_webview_content_and_restore(self, scroll_pos: int):
        """
        🔥 НОВОЕ: Генерирует HTML из Markdown, устанавливает его в webview и 
        запускает процесс восстановления позиции прокрутки.
        """
        md_content = self.editor.toPlainText()
        
        # Конвертация Markdown в HTML. Добавлен nl2br для переносов строк.
        html_content = markdown.markdown(md_content, extensions=['fenced_code', 'tables', 'nl2br'])
        
        # Добавление стилей для Webview
        css_style = """
        /* ==================== СТИЛИЗАЦИЯ SCROLLBAR ВНУТРИ WEBVİEW ==================== */
        /* Webkit/Blink Scrollbar Styles (для QWebEngineView) */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
            background: #2a2a2a; /* Фон скроллбара */
        }
        
        ::-webkit-scrollbar-thumb {
            background: #4a4a4a; /* Ползунок */
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #00ff85; /* Ползунок при наведении */
        }
        /* ============================================================================== */
        <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #1a1a1a; color: #e0e0e0; padding: 20px; line-height: 1.6; }
        h1, h2, h3, h4, h5, h6 { color: #00ff85; margin-top: 1.2em; margin-bottom: 0.5em; border-bottom: 1px solid #333333; padding-bottom: 5px;}
        h1 { font-size: 2em; }
        h2 { font-size: 1.5em; }
        pre, code { background-color: #2a2a2a; color: #e0e0e0; padding: 0.2em 0.4em; border-radius: 3px; font-family: 'Consolas', monospace; }
        pre { padding: 10px; overflow-x: auto; }
        a { color: #ffcc66; text-decoration: none; }
        a:hover { text-decoration: underline; }
        table { border-collapse: collapse; width: 100%; margin: 1em 0; background-color: #232323; }
        th, td { border: 1px solid #4a4a4a; padding: 8px; text-align: left; }
        th { background-color: #333333; color: #00ff85; }
        img { max-width: 100%; height: auto; border: 1px solid #333333; border-radius: 4px; display: block; margin: 10px 0; }
        ul, ol { margin-left: 20px; padding-left: 0; }
        li { margin-bottom: 5px; }
        hr { border: 0; height: 1px; background-color: #333333; margin: 20px 0; }
        p { margin: 0.8em 0; }
        
        /* Цитаты */
        blockquote { 
            border-left: 5px solid #ffcc66; 
            padding: 10px 15px; 
            margin: 15px 0; 
            background-color: #232323; 
            border-radius: 4px; 
            font-style: italic; 
            color: #cccccc;
        }
        </style>
        """
        final_html = f"<!DOCTYPE html><html><head>{css_style}</head><body>{html_content}</body></html>"
        
        # 1. Установка желаемой позиции прокрутки
        self._pending_scroll_pos = scroll_pos
        
        # 2. Если scroll_pos > 0, нужно восстановить прокрутку после загрузки.
        # Подключаем временный обработчик loadFinished
        if self._pending_scroll_pos > 0:
            try:
                self.webview.loadFinished.connect(self._restore_scroll_on_load)
            except TypeError:
                pass
                
        # 3. Загрузка HTML. Это действие (self.webview.setHtml) вызывает сигнал loadFinished
        self.webview.setHtml(final_html)


    def update_webview(self):
        """Обновляет содержимое Webview на основе Markdown."""
        md_content = self.editor.toPlainText()
        
        # Конвертация Markdown в HTML
        html_content = markdown.markdown(md_content, extensions=['fenced_code', 'tables'])
        
        # Добавление стилей для Webview
        css_style = """
        <style>
        /* ==================== СТИЛИЗАЦИЯ SCROLLBAR ВНУТРИ WEBVİEW ==================== */
        /* Webkit/Blink Scrollbar Styles (для QWebEngineView) */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
            background: #1a1a1a; /* Цвет фона страницы */
        }
        
        ::-webkit-scrollbar-thumb {
            background: #4a4a4a; /* Ползунок */
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #00ff85; /* Ползунок при наведении - акцентный цвет */
        }
        /* ============================================================================== */

        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #1a1a1a; color: #e0e0e0; padding: 20px; line-height: 1.6; }
        h1, h2, h3, h4, h5, h6 { color: #00ff85; margin-top: 1.2em; margin-bottom: 0.5em; border-bottom: 1px solid #333333; padding-bottom: 5px;}
        h1 { font-size: 2em; }
        h2 { font-size: 1.5em; }
        pre, code { background-color: #2a2a2a; color: #e0e0e0; padding: 0.2em 0.4em; border-radius: 3px; font-family: 'Consolas', monospace; }
        pre { padding: 10px; overflow-x: auto; }
        a { color: #ffcc66; text-decoration: none; }
        a:hover { text-decoration: underline; }
        table { border-collapse: collapse; width: 100%; margin: 1em 0; background-color: #232323; }
        th, td { border: 1px solid #4a4a4a; padding: 8px; text-align: left; }
        th { background-color: #333333; color: #00ff85; }
        img { max-width: 100%; height: auto; border: 1px solid #333333; border-radius: 4px; display: block; margin: 10px 0; }
        ul, ol { margin-left: 20px; padding-left: 0; }
        li { margin-bottom: 5px; }
        hr { border: 0; height: 1px; background-color: #333333; margin: 20px 0; }
        p { margin: 0.8em 0; }
        
        /* Цитаты */
        blockquote { 
            border-left: 5px solid #ffcc66; 
            padding: 10px 15px; 
            margin: 15px 0; 
            background-color: #232323; 
            border-radius: 4px; 
            font-style: italic; 
            color: #cccccc;
        }
        </style>
        """
        final_html = f"<!DOCTYPE html><html><head>{css_style}</head><body>{html_content}</body></html>"
        self.webview.setHtml(final_html)
    
    # ==================== КОНЕЦ БЛОКА СИНХРОНИЗАЦИИ ====================

    def update_webview_content(self, md_content: str):
        """Немедленно обновляет Webview без задержки таймера, используется при загрузке."""
        self.editor.setPlainText(md_content)
        self.timer.start(50)

    def on_content_changed(self):
        """Обрабатывает изменение контента в редакторе."""
        # 🔥 ИСПРАВЛЕНИЕ: Игнорируем изменения от читателей и проверяем существование кнопок
        if not self.is_editable:
            return 
            
        if self.editor.toPlainText() != self.original_content and self.current_guide_fn:
            self.content_changed = True
            if self.action_save: self.action_save.setEnabled(True)
            if self.btn_cancel: self.btn_cancel.show()
            self.timer.start(500)
        else:
            self.content_changed = False
            if self.action_save: self.action_save.setEnabled(False)
            if self.btn_cancel: self.btn_cancel.hide()

    def cancel_edit(self):
        """Отменяет все несохраненные изменения."""
        if self.current_guide_fn and self.is_editable:
            self.editor.setPlainText(self.original_content)
            self.content_changed = False
            if self.action_save: self.action_save.setEnabled(False)
            if self.btn_cancel: self.btn_cancel.hide()
            self.update_webview()
            self.set_status_ok("Изменения отменены.", 2000)

    def save_current_guide(self):
        """Сохраняет текущий контент гайда в Firestore."""
        if not self.current_guide_fn or not self.is_editable:
            return
            
        new_content = self.editor.toPlainText()
        
        if save_guide_firestore(self.current_guide_fn, new_content):
            self.original_content = new_content
            self.content_changed = False
            if self.action_save: self.action_save.setEnabled(False)
            if self.btn_cancel: self.btn_cancel.hide()
            self.set_status_ok("Гайд успешно сохранен в облаке.", 3000)
            self.update_webview()
        else:
            self.set_status_error("Не удалось сохранить гайд. Проверьте подключение.", 0)

    # ==================== ДИАЛОГИ АДМИНИСТРИРОВАНИЯ ====================

    def show_user_management_dialog(self):
        """Показывает диалог управления пользователями."""
        if self.user_role == 'admin':
            dialog = UserManagementDialog(self)
            dialog.exec()
            
    def show_guide_management_dialog(self):
        """Показывает диалог управления структурой гайдов."""
        if self.user_role == 'admin':
            dialog = GuideManagementDialog(self)
            dialog.exec()
            self.repopulate_tree()

    # ==================== СТАТУС БАР И ВЫХОД ====================

    def logout(self):
        """Выход из системы и возвращение к окну входа."""
        # Логика проверки несохраненных изменений
        if self.content_changed and self.is_editable:
            reply = QMessageBox.question(self, "Несохраненные изменения", 
                "У вас есть несохраненные изменения. Сохранить перед выходом?", 
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)

            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Yes:
                self.save_current_guide()
                if self.content_changed: 
                    return
                    
        logging.info(f"Пользователь {self.user_role.upper()} вышел из системы.")
        
        # 1. Скрываем главное окно
        self.hide() 

        # 2. Показываем окно входа (parent_dialog)
        if self.parent_dialog:
            self.parent_dialog.show()
            
        # 🔥 КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: Безопасное удаление старого экземпляра MainWindow.
        # Это предотвратит его конфликт с новым окном при повторном входе.
        self.deleteLater()

    def closeEvent(self, event):
        """Обрабатывает закрытие окна (нажатие на 'X'), проверяя несохраненные изменения."""
        if self.content_changed and self.is_editable:
            reply = QMessageBox.question(self, "Несохраненные изменения", 
                "У вас есть несохраненные изменения. Сохранить перед выходом?", 
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)

            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

            if reply == QMessageBox.StandardButton.Yes:
                self.save_current_guide()
                if self.content_changed: 
                    event.ignore()
                    return
        
        # 🔥 ИСПРАВЛЕНИЕ: При закрытии на 'X' завершаем приложение. 
        # Логика показа parent_dialog здесь удалена, так как она противоречит 
        # QApplication.instance().quit().
        QApplication.instance().quit() 
        event.accept()

    def set_status_ok(self, message, timeout=2000):
        """Устанавливает статусную строку (успех)."""
        self.statusBar().setStyleSheet("QStatusBar::item {border: none;} QLabel { color: #00ff85; }")
        self.statusBar().showMessage(message, timeout)
        
    def set_status_error(self, message, timeout=0):
        """Устанавливает статусную строку (ошибка)."""
        self.statusBar().setStyleSheet("QStatusBar::item {border: none;} QLabel { color: #ff6b6b; }")
        self.statusBar().showMessage(f"Ошибка: {message}", timeout)
        
    def rename_guide_in_db(self, doc_id: str, old_title: str, new_title: str) -> bool:
        if doc_id in ['root_info', 'folder_maps', 'root_settings']:
             return False
        return rename_node(doc_id, new_title)
        
    def delete_guide_from_db(self, doc_id: str) -> bool:
        return delete_node_recursively(doc_id)