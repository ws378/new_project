from ..command_manager import Command
from ...models.annotations import Annotations, AreaLabel
from ...utils.room_identity import area_room_id
from typing import List, Tuple


class SplitAreaLabelCommand(Command):
    """切割区域标签命令：删除原始区域，添加两个新区域，支持撤销。"""

    def __init__(
        self,
        annotations: Annotations,
        original_label: AreaLabel,
        polygon1: List[Tuple[float, float]],
        polygon2: List[Tuple[float, float]],
        refresh_cb=None,
    ):
        self.annotations = annotations
        self.original_label = original_label
        self.polygon1 = polygon1
        self.polygon2 = polygon2
        self.refresh_cb = refresh_cb
        self.new_label1: AreaLabel | None = None
        self.new_label2: AreaLabel | None = None
        self._restored_original_id: str | None = None

    def execute(self):
        ann = self.annotations
        orig = self.original_label

        orig_room_id = area_room_id(orig)

        if self.new_label1 is not None and self.new_label2 is not None:
            # Redo path: remove restored original and old new_labels, re-add with stored IDs
            if self._restored_original_id is not None:
                ann.remove_by_id(self._restored_original_id)
                self._restored_original_id = None
            ann.area_labels = [a for a in ann.area_labels if a.id != self.new_label1.id]
            ann.area_labels = [a for a in ann.area_labels if a.id != self.new_label2.id]
            self.new_label1 = ann.add_area_label(
                self.polygon1, area_id=self.new_label1.area_id
            )
            self.new_label2 = ann.add_area_label(
                self.polygon2, area_id=self.new_label2.area_id
            )
        else:
            # First execution: delete original, add two new
            ann.remove_by_id(orig.id)
            self.new_label1 = ann.add_area_label(self.polygon1)
            self.new_label2 = ann.add_area_label(self.polygon2)

        if self.refresh_cb:
            self.refresh_cb()

        print(
            f"Split area {orig_room_id} -> {area_room_id(self.new_label1)}, {area_room_id(self.new_label2)}"
        )

    def undo(self):
        if self.new_label1 is None or self.new_label2 is None:
            return
        ann = self.annotations
        # Remove the two new labels
        ann.remove_by_id(self.new_label1.id)
        ann.remove_by_id(self.new_label2.id)
        # Restore original (reuse its original area_id)
        orig = self.original_label
        restored = ann.add_area_label(orig.polygon, area_id=area_room_id(orig))
        self._restored_original_id = restored.id
        if self.refresh_cb:
            self.refresh_cb()
