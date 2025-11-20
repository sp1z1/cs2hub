# views/custom_tree_view.py
from PyQt6.QtWidgets import QTreeView
from PyQt6.QtCore import Qt, QTimer, QModelIndex
from PyQt6.QtGui import QStandardItemModel, QStandardItem
import qtawesome as qta


class CustomTreeView(QTreeView):
    def __init__(self, handler=None):
        super().__init__()
        self.handler = handler

        self.model = QStandardItemModel()
        self.setModel(self.model)
        self.setHeaderHidden(True)
        self.setIndentation(24)
        self.setAnimated(True)
        self.setExpandsOnDoubleClick(True)

        # Drag & Drop
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeView.DragDropMode.InternalMove)
        self.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)

        # ← ВОТ ЭТО КРИТИЧНО: включаем контекстное меню!
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Стиль
        self.setStyleSheet("""
            QTreeView {
                background: #121212; /* Фон как в MainWindow */
                border: none;
                color: #e0e0e0;
                /* --- Ключевое изменение 1: Отключаем выделение строки декором --- */
                show-decoration-selected: 0; 
                outline: none; 
            }
            
            QTreeView::item {
                padding: 6px 4px; 
                margin: 2px 0;
                border-radius: 4px;
                border: none;
            }

            QTreeView::item:hover {
                /* Фон, как при наведении в MainWindow */
                background: #1e1e1e; 
                /* Зеленый цвет текста */
                color: #00ff85;
            }
            
            QTreeView::item:selected {
                /* --- Ключевое изменение 2: Делаем фон похожим на hover --- */
                background: #1e1e1e; 
                /* --- Ключевое изменение 3: Устанавливаем зеленый текст --- */
                color: #00ff85; 
                border: none;
                outline: none;
            }
            
            QTreeView::item:selected:active {
                /* Делаем его чуть заметно темнее */
                background: #1a1a1a;
                color: #00ff85;
            }
        """)
    def dragMoveEvent(self, event):
        """Строгий запрет на сброс в гайд (guide)."""
        
        # 1. Сначала вызываем стандартный обработчик для базовой логики D&D
        super().dragMoveEvent(event)
        
        # 2. Если D&D не включен или событие не принято, выходим
        if event.dropAction() == Qt.DropAction.IgnoreAction or not event.isAccepted():
            return

        # 3. Получаем индекс элемента, над которым находится курсор (цель сброса)
        target_index: QModelIndex = self.indexAt(event.position().toPoint())
        
        # Если нет элемента (например, сброс в корень или в пустую область), 
        # или если это гайд, мы должны проверить DropIndicatorPosition.
        # QAbstractItemView.DropIndicatorPosition сообщает, куда будет сброс:
        # - OnItem: Сброс В элемент (делает его родителем)
        # - AboveItem/BelowItem: Сброс рядом (делает его соседом)

        drop_pos = self.dropIndicatorPosition()

        if target_index.isValid() and drop_pos == QTreeView.DropIndicatorPosition.OnItem:
            target_item = self.model.itemFromIndex(target_index)
            if target_item:
                node_type = target_item.data(Qt.ItemDataRole.UserRole + 1)
                
                # Строго запрещаем сброс В элемент типа 'guide'
                if node_type == 'guide':
                    event.ignore() # Игнорируем событие сброса
                    return
        
        # Для остальных случаев (folder, root, above/below) - разрешаем стандартное действие
        event.accept()

    def dropEvent(self, event):
        super().dropEvent(event)
        if self.handler and hasattr(self.handler, 'handle_tree_structure_change_after_drop'):
            QTimer.singleShot(50, self.handler.handle_tree_structure_change_after_drop)