from ..command_manager import Command
import copy

class UpdateAnnotationCommand(Command):
    """更新标注的几何坐标命令 (支持移动和修改顶点)"""
    def __init__(self, item, old_state, new_state, refresh_cb=None, annotations=None):
        self.item = item
        # Copy to avoid reference mutations
        self.old_state = copy.deepcopy(old_state)
        self.new_state = copy.deepcopy(new_state)
        self.refresh_cb = refresh_cb
        self.annotations = annotations

    def execute(self):
        self._apply_state(self.new_state)

    def undo(self):
        self._apply_state(self.old_state)

    def _apply_state(self, state):
        if hasattr(self.item, 'polygon'):
            self.item.polygon = copy.deepcopy(state)
        elif hasattr(self.item, 'points'):
            self.item.points = copy.deepcopy(state)
        elif hasattr(self.item, 'start') and hasattr(self.item, 'end'):
            self.item.start, self.item.end = copy.deepcopy(state)
        elif hasattr(self.item, 'position'):
            # For Station, state is a tuple (position, orientation)
            self.item.position = tuple(state[0])
            self.item.orientation = state[1]

        if self.annotations is not None and hasattr(self.annotations, "sync_constraint_views"):
            self.annotations.sync_constraint_views()

        if self.refresh_cb:
            self.refresh_cb()
