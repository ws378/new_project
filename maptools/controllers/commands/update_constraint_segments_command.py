from __future__ import annotations

import copy

from ..command_manager import Command


class UpdateConstraintSegmentsCommand(Command):
    """Replace the formal constraint-segment truth as a single undoable step."""

    def __init__(self, annotations, old_segments, new_segments, refresh_cb=None):
        self.annotations = annotations
        self.old_segments = copy.deepcopy(old_segments)
        self.new_segments = copy.deepcopy(new_segments)
        self.refresh_cb = refresh_cb

    def execute(self):
        self._apply(self.new_segments)

    def undo(self):
        self._apply(self.old_segments)

    def _apply(self, segments):
        self.annotations.constraint_segments = copy.deepcopy(segments)
        self.annotations.sync_constraint_views()
        if self.refresh_cb:
            self.refresh_cb()
