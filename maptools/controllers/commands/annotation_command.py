from ..command_manager import Command
import uuid
from ...utils.constraint_styles import constraint_base_color

class AddAnnotationCommand(Command):
    """添加标注命令"""
    def __init__(self, annotations, item_type, data, refresh_cb=None):
        self.annotations = annotations
        self.item_type = item_type # 'forbidden', 'virtual_wall', 'station'
        self.data = data # dict or tuple params
        self.created_item = None # Store the created item to remove it on undo
        self.refresh_cb = refresh_cb

    def execute(self):
        if self.item_type == 'forbidden':
            self.created_item = self.annotations.add_constraint_segment(
                self.data,
                closed=True,
                constraint_type="forbidden_zone",
                name="Forbidden Zone",
                item_id=self.created_item.id if self.created_item else None,
                color=constraint_base_color("forbidden_zone"),
            )
        elif self.item_type == 'pass_only':
            self.created_item = self.annotations.add_constraint_segment(
                self.data,
                closed=True,
                constraint_type="pass_only",
                name="Pass Only Zone",
                item_id=self.created_item.id if self.created_item else None,
                color=constraint_base_color("pass_only"),
            )
        elif self.item_type == 'virtual_wall':
            self.created_item = self.annotations.add_constraint_segment(
                [self.data[0], self.data[1]],
                closed=False,
                constraint_type="virtual_wall",
                name="Virtual Wall",
                item_id=self.created_item.id if self.created_item else None,
                color=constraint_base_color("virtual_wall"),
            )
        elif self.item_type == 'station':
            self.created_item = self.annotations.add_station(self.data[0], self.data[1])
        elif self.item_type == 'area_label':
            # data is dict: {'polygon': [...], 'name': '...'}
            # On redo, reuse the original area_id to keep consistency
            area_id = self.created_item.area_id if self.created_item else self.data.get('area_id')
            self.created_item = self.annotations.add_area_label(
                self.data['polygon'], name=self.data['name'], area_id=area_id
            )

        if self.refresh_cb:
            self.refresh_cb()

    def undo(self):
        if self.created_item:
            self.annotations.remove_by_id(self.created_item.id)
            if self.refresh_cb:
                self.refresh_cb()

# TODO: RemoveAnnotationCommand (如果未来支持删除/编辑)
