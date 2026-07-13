import tkinter as tk
from tkinter import simpledialog
from .theme import COLORS, FONTS, SPACING


class RotationDialog(simpledialog.Dialog):
    def __init__(self, parent, title="Rotate Map"):
        self.angle = 0.0
        self.interpolation_mode = "nearest"
        super().__init__(parent, title)

    def body(self, master):
        master.configure(bg=COLORS["bg_primary"])
        tk.Label(master, text="旋转角度（度）：",
                 bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
                 font=FONTS["body"]).grid(row=0, sticky=tk.W, padx=8, pady=4)
        tk.Label(master, text="（逆时针为正）",
                 bg=COLORS["bg_primary"], fg=COLORS["fg_secondary"],
                 font=FONTS["caption"]).grid(row=1, sticky=tk.W, padx=8)

        self.e1 = tk.Entry(
            master, width=12,
            bg=COLORS["bg_surface"], fg=COLORS["fg_bright"],
            insertbackground=COLORS["fg_primary"],
            relief=tk.FLAT, bd=1, font=FONTS["body"],
        )
        self.e1.grid(row=0, column=1, padx=8, pady=4)
        self.e1.insert(0, "0.0")

        tk.Label(master, text="图像插值：",
                 bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
                 font=FONTS["body"]).grid(row=2, sticky=tk.W, padx=8, pady=(8, 4))
        self.interpolation_var = tk.StringVar(value="nearest")
        for row, (text, value) in enumerate([
            ("保真栅格", "nearest"),
            ("平滑显示", "smooth"),
        ]):
            tk.Radiobutton(
                master, text=text, variable=self.interpolation_var, value=value,
                bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
                activebackground=COLORS["bg_primary"],
                selectcolor=COLORS["bg_surface"],
                font=FONTS["body"],
            ).grid(row=2 + row, column=1, sticky=tk.W, padx=8)
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
        master.configure(bg=COLORS["bg_primary"])
        tk.Label(master, text="Release mouse to finish crop selection.",
                 bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
                 font=FONTS["body"]).grid(row=0, sticky=tk.W, padx=8, pady=4)
        tk.Label(master, text=f"Selected size: {self.width_px} x {self.height_px} px",
                 bg=COLORS["bg_primary"], fg=COLORS["fg_secondary"],
                 font=FONTS["body"]).grid(row=1, sticky=tk.W, padx=8)
        return None

    def buttonbox(self):
        box = tk.Frame(self, bg=COLORS["bg_primary"])
        tk.Button(
            box, text="Crop", width=10, command=self.ok, default=tk.ACTIVE,
            bg=COLORS["accent"], fg=COLORS["fg_on_accent"],
            activebackground=COLORS["accent_hover"],
            relief=tk.FLAT, bd=0, font=FONTS["button"], cursor="hand2",
        ).pack(side=tk.LEFT, padx=SPACING["md"], pady=SPACING["md"])
        tk.Button(
            box, text="Cancel", width=10, command=self.cancel,
            bg=COLORS["bg_surface"], fg=COLORS["fg_primary"],
            activebackground=COLORS["bg_hover"],
            relief=tk.FLAT, bd=0, font=FONTS["button"], cursor="hand2",
        ).pack(side=tk.LEFT, padx=SPACING["md"], pady=SPACING["md"])
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def apply(self):
        self.confirmed = True
