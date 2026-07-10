from .base_tool import BaseTool

class PanTool(BaseTool):
    name = "pan"
    cursor = "fleur"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.drag_start_x = 0
        self.drag_start_y = 0

    def on_press(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def on_drag(self, event):
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y

        self.canvas.pan_offset_x += dx
        self.canvas.pan_offset_y += dy

        self.drag_start_x = event.x
        self.drag_start_y = event.y

        self.canvas.move("all", dx, dy)

    def on_release(self, event):
        # Full refresh on release to correct any drift and update viewport rendering
        self.canvas.refresh()
