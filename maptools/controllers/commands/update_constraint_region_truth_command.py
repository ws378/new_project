from __future__ import annotations

import copy

from ..command_manager import Command


class UpdateConstraintRegionTruthCommand(Command):
    """Replace formal vector/raster constraint truths in one undoable step."""

    def __init__(
        self,
        annotations,
        old_segments,
        new_segments,
        old_regions,
        new_regions,
        refresh_cb=None,
    ):
        self.annotations = annotations
        self.old_segments = copy.deepcopy(old_segments)
        self.new_segments = copy.deepcopy(new_segments)
        self.old_regions = copy.deepcopy(old_regions)
        self.new_regions = copy.deepcopy(new_regions)
        self.refresh_cb = refresh_cb

    def execute(self):
        self._apply(self.new_segments, self.new_regions)

    def undo(self):
        self._apply(self.old_segments, self.old_regions)

    def _apply(self, segments, regions):
        self.annotations.constraint_segments = copy.deepcopy(segments)
        self.annotations.derived_constraint_regions = copy.deepcopy(regions)
        self.annotations.sync_constraint_views()
        if self.refresh_cb:
            self.refresh_cb()
