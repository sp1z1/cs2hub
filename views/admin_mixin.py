# views/admin_mixin.py
from views.admin_dialogs import UserManagementDialog, GuideManagementDialog


class AdminMixin:
    def show_user_management_dialog(self):
        if self.user_role == "admin":
            UserManagementDialog(self).exec()

    def show_guide_management_dialog(self):
        if self.user_role == "admin":
            GuideManagementDialog(self).exec()
            self.repopulate_tree()