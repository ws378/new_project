import tkinter as tk
from tkinter import simpledialog

class RotationDialog(simpledialog.Dialog):
    def __init__(self, parent, title="Rotate Map"):
        self.angle = 0.0
        self.interpolation_mode = "nearest"
        super().__init__(parent, title)

    def body(self, master):
        tk.Label(master, text="旋转角度（度）：").grid(row=0, sticky=tk.W)
        tk.Label(master, text="（逆时针为正）").grid(row=1, sticky=tk.W)

        self.e1 = tk.Entry(master)
        self.e1.grid(row=0, column=1)
        self.e1.insert(0, "0.0")

        tk.Label(master, text="图像插值：").grid(row=2, sticky=tk.W)
        self.interpolation_var = tk.StringVar(value="nearest")
        tk.Radiobutton(master, text="保真栅格", variable=self.interpolation_var, value="nearest").grid(row=2, column=1, sticky=tk.W)
        tk.Radiobutton(master, text="平滑显示", variable=self.interpolation_var, value="smooth").grid(row=3, column=1, sticky=tk.W)
        return self.e1

    def apply(self):
        try:
            self.angle = float(self.e1.get())
        except ValueError:
            self.angle = 0.0
        self.interpolation_mode = self.interpolation_var.get()


class CropInfoDialog(simpledialog.Dialog):
    def __init__(self, parent, width_px: int, height_px: int, title="Crop Map"):
        self.width_px = width_px
        self.height_px = height_px
        self.confirmed = False
        super().__init__(parent, title)

    def body(self, master):
        tk.Label(master, text="Release mouse to finish crop selection.").grid(row=0, sticky=tk.W)
        tk.Label(master, text=f"Selected size: {self.width_px} x {self.height_px} px").grid(row=1, sticky=tk.W)
        return None

    def buttonbox(self):
        box = tk.Frame(self)
        tk.Button(box, text="Crop", width=10, command=self.ok, default=tk.ACTIVE).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(box, text="Cancel", width=10, command=self.cancel).pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def apply(self):
        self.confirmed = True
