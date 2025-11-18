from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt, QModelIndex, QMimeData, QPoint
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tree_handler import TreeHandlerMixin

class CustomTreeWidget(QTreeWidget):
    """
    QTreeWidget, переопределенный для обработки событий Drag and Drop.
    """
    def __init__(self, parent=None, handler: 'TreeHandlerMixin' = None):
        super().__init__(parent)
        self.handler = handler 

    # 1. КОНТРОЛЬ ВИЗУАЛЬНОГО DROP (DragMoveEvent)
    # Определяет, куда можно ПЕРЕМЕСТИТЬ элемент (контролирует индикатор drop)
    def dragMoveEvent(self, event):
        # Получаем элемент, который находится под курсором
        target_item = self.itemAt(event.position().toPoint())
        
        # ------------------------------------------------------------------
        # ИСПРАВЛЕНИЕ: Разрешить Drop в корень (когда target_item is None)
        # ------------------------------------------------------------------
        if target_item is None:
            # Если курсор находится над пустым пространством, разрешаем Drop.
            super().dragMoveEvent(event)
            return

        # Если курсор находится над элементом
        if target_item:
            # Читаем тип узла
            node_type: Any = target_item.data(0, Qt.ItemDataRole.UserRole + 1)
            
            # Если целевой элемент - гайд, запрещаем drop.
            if node_type == 'guide':
                event.ignore()
                return

        # Для папок используем стандартное поведение
        super().dragMoveEvent(event)


    # 2. ФУНКЦИОНАЛЬНЫЙ КОНТРОЛЬ DROP (DropMimeData)
    # Определяет, можно ли принять данные (необходимо для подтверждения, что родитель — не гайд)
    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QTreeWidgetItem | None) -> bool:
        # Если drop происходит на какой-либо элемент (т.е. не в корень дерева)
        if parent:
            # Читаем тип целевого родителя
            node_type: Any = parent.data(0, Qt.ItemDataRole.UserRole + 1)
            
            # Если целевой родитель - гайд, запрещаем drop.
            if node_type == 'guide':
                return False 
        
        # Если drop в корень (parent is None) или на папку, разрешаем стандартную обработку.
        return super().dropMimeData(data, action, row, column, parent)


    # 3. ОБРАБОТЧИК ПОСЛЕ УСПЕШНОГО DROP (DropEvent)
    def dropEvent(self, event):
        # Позволяем стандартному обработчику QTreeWidget выполнить перемещение
        super().dropEvent(event)
        
        # Получаем только что перемещенный элемент
        moved_item = self.currentItem() 

        if moved_item and self.handler:
            self.handler.handle_tree_structure_change(moved_item)

        event.accept()