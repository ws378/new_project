"""
统一视觉主题系统 - 为所有 UI 组件提供一致的色板、字体和间距。
"""

import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# 色板
# ---------------------------------------------------------------------------
COLORS = {
    # 背景
    "bg_root": "#1e1e1e",
    "bg_primary": "#252526",
    "bg_secondary": "#2d2d2d",
    "bg_surface": "#333333",
    "bg_surface_alt": "#3a3a3a",
    "bg_hover": "#454545",
    "bg_active": "#4a9eff",
    "bg_selected": "#264f78",
    # 前景
    "fg_primary": "#cccccc",
    "fg_secondary": "#999999",
    "fg_muted": "#666666",
    "fg_bright": "#e0e0e0",
    "fg_on_accent": "#ffffff",
    # 强调色
    "accent": "#4a9eff",
    "accent_hover": "#6bb3ff",
    "accent_pressed": "#3a8de8",
    # 语义色
    "success": "#4caf50",
    "warning": "#ff9800",
    "error": "#f44336",
    "info": "#2196f3",
    # 边框
    "border": "#3e3e3e",
    "border_light": "#555555",
    "border_focus": "#4a9eff",
    # 工具栏 / 状态栏
    "toolbar_bg": "#2d2d2d",
    "toolbar_border": "#3e3e3e",
    "statusbar_bg": "#007acc",
    "statusbar_fg": "#ffffff",
    "session_bg": "#252526",
    # 侧边栏
    "sidebar_bg": "#252526",
    "sidebar_header_bg": "#333333",
    # Tooltip
    "tooltip_bg": "#2d2d2d",
    "tooltip_fg": "#cccccc",
    "tooltip_border": "#4a9eff",
}

# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------
_FONT_FAMILY = "Noto Sans"
_FONT_FAMILY_MONO = "DejaVu Sans Mono"

FONTS = {
    "heading": (_FONT_FAMILY, 10, "bold"),
    "body": (_FONT_FAMILY, 9),
    "body_bold": (_FONT_FAMILY, 9, "bold"),
    "caption": (_FONT_FAMILY, 8),
    "mono": (_FONT_FAMILY_MONO, 9),
    "button": (_FONT_FAMILY, 9),
    "menu": (_FONT_FAMILY, 9),
    "status": (_FONT_FAMILY, 9),
    "session": (_FONT_FAMILY, 9),
    "tooltip": (_FONT_FAMILY, 8),
}

# ---------------------------------------------------------------------------
# 间距
# ---------------------------------------------------------------------------
SPACING = {
    "xs": 2,
    "sm": 4,
    "md": 8,
    "lg": 12,
    "xl": 16,
    "xxl": 24,
}

# ---------------------------------------------------------------------------
# 宽度
# ---------------------------------------------------------------------------
WIDTHS = {
    "sidebar": 210,
    "toolbar_button": 6,
    "entry": 12,
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def styled_button(parent, text, command=None, **kwargs):
    """创建统一风格的按钮。"""
    defaults = {
        "text": text,
        "command": command,
        "bg": COLORS["bg_surface"],
        "fg": COLORS["fg_primary"],
        "activebackground": COLORS["bg_hover"],
        "activeforeground": COLORS["fg_bright"],
        "relief": tk.FLAT,
        "bd": 0,
        "padx": SPACING["md"],
        "pady": SPACING["sm"],
        "font": FONTS["button"],
        "cursor": "hand2",
    }
    defaults.update(kwargs)
    btn = tk.Button(parent, **defaults)

    def _on_enter(_e):
        if btn["state"] != tk.DISABLED:
            btn.config(bg=COLORS["bg_hover"])

    def _on_leave(_e):
        if btn["state"] != tk.DISABLED:
            btn.config(bg=COLORS["bg_surface"])

    btn.bind("<Enter>", _on_enter)
    btn.bind("<Leave>", _on_leave)
    return btn


def styled_label(parent, **kwargs):
    """创建统一风格的标签。"""
    defaults = {
        "bg": kwargs.pop("bg", COLORS["bg_primary"]),
        "fg": kwargs.pop("fg", COLORS["fg_primary"]),
        "font": kwargs.pop("font", FONTS["body"]),
    }
    defaults.update(kwargs)
    return tk.Label(parent, **defaults)


def styled_entry(parent, **kwargs):
    """创建统一风格的输入框。"""
    defaults = {
        "bg": COLORS["bg_surface"],
        "fg": COLORS["fg_bright"],
        "insertbackground": COLORS["fg_primary"],
        "relief": tk.FLAT,
        "bd": 1,
        "font": FONTS["body"],
    }
    defaults.update(kwargs)
    return tk.Entry(parent, **defaults)


def styled_checkbutton(parent, **kwargs):
    """创建统一风格的复选框。"""
    defaults = {
        "bg": kwargs.pop("bg", COLORS["bg_primary"]),
        "fg": COLORS["fg_primary"],
        "activebackground": COLORS["bg_primary"],
        "activeforeground": COLORS["fg_bright"],
        "selectcolor": COLORS["bg_surface"],
        "font": FONTS["body"],
    }
    defaults.update(kwargs)
    return tk.Checkbutton(parent, **defaults)


def styled_label_frame(parent, **kwargs):
    """创建统一风格的 LabelFrame。"""
    defaults = {
        "bg": kwargs.pop("bg", COLORS["bg_primary"]),
        "fg": COLORS["fg_primary"],
        "font": FONTS["body_bold"],
        "relief": tk.FLAT,
        "bd": 1,
    }
    defaults.update(kwargs)
    return tk.LabelFrame(parent, **defaults)


def styled_frame(parent, **kwargs):
    """创建统一风格的 Frame。"""
    defaults = {
        "bg": kwargs.pop("bg", COLORS["bg_primary"]),
    }
    defaults.update(kwargs)
    return tk.Frame(parent, **defaults)


def styled_radiobutton(parent, **kwargs):
    """创建统一风格的单选按钮。"""
    defaults = {
        "bg": kwargs.pop("bg", COLORS["bg_primary"]),
        "fg": COLORS["fg_primary"],
        "activebackground": COLORS["bg_primary"],
        "activeforeground": COLORS["fg_bright"],
        "selectcolor": COLORS["bg_surface"],
        "font": FONTS["body"],
    }
    defaults.update(kwargs)
    return tk.Radiobutton(parent, **defaults)


# ---------------------------------------------------------------------------
# ttk 主题
# ---------------------------------------------------------------------------

def apply_theme(root):
    """应用统一主题到根窗口和 ttk.Style。"""
    root.configure(bg=COLORS["bg_root"])

    style = ttk.Style(root)

    # 尝试使用 clam 主题作为基础
    available = style.theme_names()
    if "clam" in available:
        style.theme_use("clam")

    # 全局 ttk 样式
    style.configure(".", **{
        "background": COLORS["bg_primary"],
        "foreground": COLORS["fg_primary"],
        "fieldbackground": COLORS["bg_surface"],
        "insertcolor": COLORS["fg_primary"],
        "font": FONTS["body"],
    })

    # Notebook (标签页)
    style.configure("TNotebook", **{
        "background": COLORS["bg_primary"],
        "borderwidth": 0,
    })
    style.configure("TNotebook.Tab", **{
        "background": COLORS["bg_surface"],
        "foreground": COLORS["fg_secondary"],
        "padding": [12, 4],
        "font": FONTS["body"],
    })
    style.map("TNotebook.Tab", **{
        "background": [
            ("selected", COLORS["bg_active"]),
            ("active", COLORS["bg_hover"]),
        ],
        "foreground": [
            ("selected", COLORS["fg_on_accent"]),
            ("active", COLORS["fg_bright"]),
        ],
    })

    # Button
    style.configure("TButton", **{
        "background": COLORS["bg_surface"],
        "foreground": COLORS["fg_primary"],
        "borderwidth": 0,
        "padding": [8, 4],
        "font": FONTS["button"],
    })
    style.map("TButton", **{
        "background": [
            ("active", COLORS["bg_hover"]),
            ("disabled", COLORS["bg_secondary"]),
        ],
        "foreground": [
            ("disabled", COLORS["fg_muted"]),
        ],
    })

    # Accent Button
    style.configure("Accent.TButton", **{
        "background": COLORS["accent"],
        "foreground": COLORS["fg_on_accent"],
    })
    style.map("Accent.TButton", **{
        "background": [
            ("active", COLORS["accent_hover"]),
            ("pressed", COLORS["accent_pressed"]),
        ],
    })

    # Entry
    style.configure("TEntry", **{
        "fieldbackground": COLORS["bg_surface"],
        "foreground": COLORS["fg_bright"],
        "insertcolor": COLORS["fg_primary"],
        "borderwidth": 1,
        "relief": "flat",
    })

    # Checkbutton
    style.configure("TCheckbutton", **{
        "background": COLORS["bg_primary"],
        "foreground": COLORS["fg_primary"],
        "indicatorcolor": COLORS["bg_surface"],
    })
    style.map("TCheckbutton", **{
        "background": [("active", COLORS["bg_primary"])],
        "indicatorcolor": [
            ("selected", COLORS["accent"]),
            ("!selected", COLORS["bg_surface"]),
        ],
    })

    # Radiobutton
    style.configure("TRadiobutton", **{
        "background": COLORS["bg_primary"],
        "foreground": COLORS["fg_primary"],
        "indicatorcolor": COLORS["bg_surface"],
    })
    style.map("TRadiobutton", **{
        "background": [("active", COLORS["bg_primary"])],
        "indicatorcolor": [
            ("selected", COLORS["accent"]),
            ("!selected", COLORS["bg_surface"]),
        ],
    })

    # Frame
    style.configure("TFrame", **{
        "background": COLORS["bg_primary"],
    })

    # LabelFrame
    style.configure("TLabelframe", **{
        "background": COLORS["bg_primary"],
        "foreground": COLORS["fg_primary"],
        "bordercolor": COLORS["border"],
        "relief": "groove",
    })
    style.configure("TLabelframe.Label", **{
        "background": COLORS["bg_primary"],
        "foreground": COLORS["fg_primary"],
        "font": FONTS["body_bold"],
    })

    # Label
    style.configure("TLabel", **{
        "background": COLORS["bg_primary"],
        "foreground": COLORS["fg_primary"],
        "font": FONTS["body"],
    })

    # Scale (Scrollbar)
    style.configure("TScale", **{
        "background": COLORS["bg_primary"],
        "troughcolor": COLORS["bg_surface"],
    })

    # Separator
    style.configure("TSeparator", **{
        "background": COLORS["border"],
    })

    # Scrollbar
    style.configure("TScrollbar", **{
        "background": COLORS["bg_surface"],
        "troughcolor": COLORS["bg_secondary"],
        "arrowcolor": COLORS["fg_secondary"],
    })

    # PanedWindow
    style.configure("TPanedwindow", **{
        "background": COLORS["border"],
    })

    # Toolbutton (用于工具栏)
    style.configure("Toolbutton", **{
        "background": COLORS["bg_surface"],
        "foreground": COLORS["fg_primary"],
        "borderwidth": 0,
        "padding": [6, 4],
        "font": FONTS["button"],
    })
    style.map("Toolbutton", **{
        "background": [
            ("active", COLORS["bg_hover"]),
            ("pressed", COLORS["bg_active"]),
        ],
        "foreground": [
            ("pressed", COLORS["fg_on_accent"]),
        ],
    })
    style.configure("Active.Toolbutton", **{
        "background": COLORS["bg_active"],
        "foreground": COLORS["fg_on_accent"],
    })

    return style
