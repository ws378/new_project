from ..command_manager import Command

class DeleteAnnotationCommand(Command):
    """删除标注命令"""
    def __init__(self, annotations, item_type, item, refresh_cb=None):
        self.annotations = annotations
        self.item_type = item_type
        self.item = item
        self.refresh_cb = refresh_cb

    def execute(self):
        self.annotations.remove_by_id(self.item.id)
        if self.refresh_cb:
            self.refresh_cb()

    def undo(self):
        # 恢复回来
        self.annotations.restore_item(self.item_type, self.item)

        if self.refresh_cb:
            self.refresh_cb()
