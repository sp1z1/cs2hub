# views/admin_mixin.py
from typing import TYPE_CHECKING
from views.admin_dialogs import UserManagementDialog, GuideManagementDialog

if TYPE_CHECKING:
    from views.main_window import MainWindow

class AdminMixin:
    def show_user_management_dialog(self):
        if self.user_role == "admin":
            dlg = UserManagementDialog(self)
            dlg.exec()

    def show_guide_management_dialog(self):
        if self.user_role == "admin":
            dlg = GuideManagementDialog(self)
            # Подключаем сигнал обновления дерева, если в админке что-то поменяли
            dlg.structure_changed.connect(self.populate_tree)
            dlg.exec()