from __future__ import annotations

import math
import os
import subprocess
import tempfile
import tkinter as tk
import yaml

from ..utils.export import Exporter

from .theme import COLORS, FONTS

FPS = 30


class PathTrackingDialog(tk.Toplevel):
    """路径跟踪动画对话框"""

    def __init__(self, parent, path_nodes, map_data):
        super().__init__(parent)
        self.title("路径跟踪动画")
        self.configure(bg=COLORS["bg_primary"])
        self.resizable(True, True)

        self._path_nodes = path_nodes
        self._map_data = map_data
        self._anim_index = 0
        self._playing = False
        self._after_id = None

        speed_frame = tk.Frame(self, bg=COLORS["bg_primary"])
        speed_frame.pack(fill=tk.X, padx=8, pady=(8, 2))

        tk.Label(
            speed_frame, text="播放速度:",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body"],
        ).pack(side=tk.LEFT)
        self._speed_var = tk.DoubleVar(value=1.0)
        self._speed_scale = tk.Scale(
            speed_frame, from_=0.5, to=10.0, resolution=0.5,
            orient=tk.HORIZONTAL, length=200,
            variable=self._speed_var,
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            troughcolor=COLORS["bg_surface"],
            highlightthickness=0, bd=0,
            font=FONTS["caption"],
        )
        self._speed_scale.pack(side=tk.LEFT, padx=4)

        self._progress_var = tk.StringVar(value="0 / 0")
        tk.Label(
            speed_frame, textvariable=self._progress_var,
            bg=COLORS["bg_primary"], fg=COLORS["fg_secondary"],
            font=FONTS["body"],
        ).pack(side=tk.RIGHT, padx=8)

        canvas_frame = tk.Frame(self, bg=COLORS["bg_primary"])
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        tk.Label(
            canvas_frame, text="完整轨迹",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"],
        ).grid(row=0, column=0, pady=(0, 2))
        tk.Label(
            canvas_frame, text="跟踪路线",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"],
        ).grid(row=0, column=1, pady=(0, 2))

        self._cw = max(700, self.winfo_screenwidth() // 2)
        self._ch = max(600, self.winfo_screenheight() // 2)
        self._left_canvas = tk.Canvas(
            canvas_frame, width=self._cw, height=self._ch,
            bg="#1a1a2e", highlightthickness=1,
            highlightbackground=COLORS["border_light"],
        )
        self._left_canvas.grid(row=1, column=0, padx=(0, 4), sticky=tk.NSEW)

        self._right_canvas = tk.Canvas(
            canvas_frame, width=self._cw, height=self._ch,
            bg="#1a1a2e", highlightthickness=1,
            highlightbackground=COLORS["border_light"],
        )
        self._right_canvas.grid(row=1, column=1, padx=(4, 0), sticky=tk.NSEW)

        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.columnconfigure(1, weight=1)
        canvas_frame.rowconfigure(1, weight=1)

        self._setup_coords()
        self._robot_radius = max(
            1.0,
            (self._x_range + self._y_range) / 2 * 0.02
        )
        self._draw_left()
        self._draw_right()

        ctrl_frame = tk.Frame(self, bg=COLORS["bg_primary"])
        ctrl_frame.pack(fill=tk.X, padx=8, pady=(4, 2))

        self._play_btn = tk.Button(
            ctrl_frame, text="▶ 播放", width=10,
            bg=COLORS.get("bg_active", "#4a90d9"),
            fg=COLORS.get("fg_on_accent", "#ffffff"),
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._toggle_play,
        )
        self._play_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._reset_btn = tk.Button(
            ctrl_frame, text="⏹ 重置", width=10,
            bg=COLORS.get("bg_surface", COLORS["bg_primary"]),
            fg=COLORS["fg_primary"],
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._reset,
        )
        self._reset_btn.pack(side=tk.LEFT)

        bottom_frame = tk.Frame(self, bg=COLORS["bg_primary"])
        bottom_frame.pack(fill=tk.X, padx=8, pady=(2, 8))

        self._send_btn = tk.Button(
            bottom_frame, text="发送到机器人", width=14,
            bg="#e67e22", fg="#ffffff",
            activebackground="#d35400", activeforeground="#ffffff",
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._send_to_robot,
        )
        self._send_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._sim_btn = tk.Button(
            bottom_frame, text="启动仿真", width=12,
            bg="#27ae60", fg="#ffffff",
            activebackground="#1e8449", activeforeground="#ffffff",
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._launch_simulation,
        )
        self._sim_btn.pack(side=tk.LEFT)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.transient(parent)
        self.grab_set()

    def _setup_coords(self):
        pts = [(n.x, n.y) for n in self._path_nodes]
        if not pts:
            self._x_range = self._y_range = 10.0
            self._origin_x = self._origin_y = 0.0
            return
        xs, ys = zip(*pts)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        margin = max((max_x - min_x) * 0.02, (max_y - min_y) * 0.02, 0.5)
        self._origin_x = min_x - margin
        self._origin_y = min_y - margin
        self._x_range = max_x - min_x + 2 * margin
        self._y_range = max_y - min_y + 2 * margin
        if self._x_range < 1.0:
            self._x_range = 10.0
        if self._y_range < 1.0:
            self._y_range = 10.0

    def _world_to_canvas(self, wx, wy, canvas):
        cw = max(float(canvas.winfo_width()), float(self._cw), 20.0)
        ch = max(float(canvas.winfo_height()), float(self._ch), 20.0)
        pad = 10
        scale = min((cw - 2 * pad) / self._x_range,
                    (ch - 2 * pad) / self._y_range)
        cx = pad + (wx - self._origin_x) * scale
        cy = (ch - pad) - (wy - self._origin_y) * scale
        return cx, cy

    def _draw_left(self):
        c = self._left_canvas
        c.delete("all")
        if not self._path_nodes:
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2,
                          text="无路径数据", fill=COLORS["fg_muted"])
            return

        coords = [self._world_to_canvas(n.x, n.y, c) for n in self._path_nodes]

        for i in range(1, len(coords)):
            c.create_line(
                coords[i - 1][0], coords[i - 1][1],
                coords[i][0], coords[i][1],
                fill="#ff8800", width=2,
            )

        if coords:
            sx, sy = coords[0]
            c.create_oval(sx - 7, sy - 7, sx + 7, sy + 7,
                          fill="#00ff00", outline="#ffffff", width=2)
            c.create_text(sx + 14, sy, text="起点", fill="#00ff00",
                          font=("Arial", 11, "bold"), anchor="w")

        if len(coords) > 1:
            ex, ey = coords[-1]
            c.create_oval(ex - 7, ey - 7, ex + 7, ey + 7,
                          fill="#ff3333", outline="#ffffff", width=2)
            c.create_text(ex + 14, ey, text="终点", fill="#ff3333",
                          font=("Arial", 11, "bold"), anchor="w")

    def _toggle_play(self):
        if self._playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        if not self._path_nodes:
            return
        self._playing = True
        self._play_btn.configure(text="⏸ 暂停")
        self._step()

    def _pause(self):
        self._playing = False
        self._play_btn.configure(text="▶ 播放")
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _reset(self):
        self._pause()
        self._anim_index = 0
        self._progress_var.set(f"0 / {len(self._path_nodes)}")
        self._draw_right()

    def _step(self):
        if not self._playing:
            return
        if self._anim_index >= len(self._path_nodes):
            self._playing = False
            self._play_btn.configure(text="▶ 重播")
            return

        self._draw_right()
        self._anim_index += 1
        delay = max(20, int(50 / self._speed_var.get()))
        self._after_id = self.after(delay, self._step)

    def _draw_right(self):
        c = self._right_canvas
        c.delete("all")
        if not self._path_nodes:
            return

        coords = [self._world_to_canvas(n.x, n.y, c) for n in self._path_nodes]
        idx = self._anim_index

        for i in range(1, min(idx + 1, len(coords))):
            alpha = max(0.3, i / max(idx, 1))
            orange = int(128 + int(127 * alpha))
            color = f"#ff{orange:02x}00"
            c.create_line(
                coords[i - 1][0], coords[i - 1][1],
                coords[i][0], coords[i][1],
                fill=color, width=4,
            )

        for i in range(idx + 1, len(coords)):
            c.create_line(
                coords[i - 1][0], coords[i - 1][1],
                coords[i][0], coords[i][1],
                fill="#555555", width=1, dash=(3, 3),
            )

        if idx < len(coords):
            rx, ry = coords[idx]
            r = max(4, self._robot_radius * 6)
            c.create_oval(rx - r - 2, ry - r - 2, rx + r + 2, ry + r + 2,
                          fill="", outline="#ffffff", width=1)
            c.create_oval(rx - r, ry - r, rx + r, ry + r,
                          fill="#ff4444", outline="#ff8888", width=2)
            if idx + 1 < len(coords):
                nx, ny = coords[idx + 1]
                angle = math.atan2(ny - ry, nx - rx)
                arr_len = r * 1.5
                ax = rx + math.cos(angle) * arr_len
                ay = ry + math.sin(angle) * arr_len
                c.create_line(rx, ry, ax, ay, fill="#ffffff", width=2,
                              arrow=tk.LAST, arrowshape=(6, 8, 4))
            c.create_text(rx + r + 10, ry, text=f"({idx + 1})",
                          fill="#ffffff", font=("Arial", 8, "bold"),
                          anchor="w")

        self._progress_var.set(f"{idx} / {len(self._path_nodes)}")

        if coords:
            sx, sy = coords[0]
            c.create_oval(sx - 5, sy - 5, sx + 5, sy + 5,
                          fill="#00ff00", outline="#ffffff", width=1)
            c.create_text(sx + 10, sy, text="S", fill="#00ff00",
                          font=("Arial", 10, "bold"), anchor="w")

    def _send_to_robot(self):
        md = self._map_data
        if md is None:
            tk.messagebox.showerror("错误", "无地图数据，无法发送", parent=self)
            return

        nodes = self._path_nodes
        if not nodes:
            tk.messagebox.showerror("错误", "无路径数据", parent=self)
            return

        poses = [{"x": float(n.x), "y": float(n.y)} for n in nodes]
        payload = {
            "map_id": getattr(md, "map_id", ""),
            "paths": [{
                "room_id": 0,
                "segments": [{"segment_id": 0, "start_index": 0, "end_index": len(poses) - 1, "type": "source_chunk"}],
                "poses": poses,
                "confirmed": False,
                "planner_diagnostics": {},
            }],
        }

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, prefix="coverage_send_")
        try:
            yaml.dump(payload, tmp, default_flow_style=False)
            tmp_path = tmp.name
            tmp.close()

            commander = os.path.join(os.path.dirname(__file__), "..", "..", "ros_nodes", "coverage_path_commander.py")
            commander = os.path.abspath(commander)
            if not os.path.isfile(commander):
                tk.messagebox.showerror("错误", f"找不到 commander 脚本: {commander}", parent=self)
                return

            self._send_btn.configure(text="发送中...", state=tk.DISABLED)
            self._proc = subprocess.Popen(
                ["python3", commander, "--yaml", tmp_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            self.after(1000, self._poll_send)
        except Exception as e:
            tk.messagebox.showerror("错误", f"发送失败: {e}", parent=self)
            self._send_btn.configure(text="发送到机器人", state=tk.NORMAL)

    def _launch_simulation(self):
        md = self._map_data
        if md is None:
            tk.messagebox.showerror("错误", "无地图数据", parent=self)
            return
        nodes = self._path_nodes
        if not nodes:
            tk.messagebox.showerror("错误", "无路径数据", parent=self)
            return

        export_dir = tempfile.mkdtemp(prefix="nav2_export_")
        try:
            exporter = Exporter(md, None)
            exporter.export(export_dir)
        except Exception as e:
            tk.messagebox.showerror("错误", f"地图导出失败: {e}", parent=self)
            return

        map_yaml = os.path.join(export_dir, "map.yaml")
        if not os.path.isfile(map_yaml):
            tk.messagebox.showerror("错误", "导出未生成 map.yaml", parent=self)
            return

        poses = [{"x": float(n.x), "y": float(n.y)} for n in nodes]
        payload = {
            "map_id": getattr(md, "map_id", ""),
            "paths": [{
                "room_id": 0,
                "segments": [{"segment_id": 0, "start_index": 0, "end_index": len(poses) - 1, "type": "source_chunk"}],
                "poses": poses,
                "confirmed": False,
                "planner_diagnostics": {},
            }],
        }
        path_yaml = os.path.join(export_dir, "coverage_path.yaml")
        with open(path_yaml, "w") as f:
            yaml.dump(payload, f, default_flow_style=False)

        rviz_config = os.path.join(os.path.dirname(__file__), "..", "..", "ros_nodes", "coverage_sim.rviz")
        rviz_config = os.path.abspath(rviz_config)

        launch_script = os.path.join(os.path.dirname(__file__), "..", "..", "ros_nodes", "launch_nav2_sim_b.py")
        launch_script = os.path.abspath(launch_script)
        if not os.path.isfile(launch_script):
            tk.messagebox.showerror("错误", f"找不到启动脚本: {launch_script}", parent=self)
            return

        self._sim_btn.configure(text="启动中...", state=tk.DISABLED)
        self._sim_proc = subprocess.Popen(
            ["python3", launch_script, "--map-yaml", map_yaml, "--path-yaml", path_yaml,
             "--rviz-config", rviz_config],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        tk.messagebox.showinfo("仿真启动", "Nav2 仿真已启动，请查看终端输出。任务完成后关闭该终端。", parent=self)
        self._sim_btn.configure(text="启动仿真", state=tk.NORMAL)

    def _poll_send(self):
        if not hasattr(self, "_proc") or self._proc is None:
            return
        ret = self._proc.poll()
        if ret is None:
            self.after(1000, self._poll_send)
            return
        out, _ = self._proc.communicate()
        self._send_btn.configure(text="发送到机器人", state=tk.NORMAL)
        if ret == 0:
            tk.messagebox.showinfo("完成", "机器人路径发送完成", parent=self)
        else:
            tk.messagebox.showerror("错误", f"路径发送失败 (exit={ret})\n{out}", parent=self)
        self._proc = None

    def _on_close(self):
        self._pause()
        if hasattr(self, "_proc") and self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        if hasattr(self, "_sim_proc") and self._sim_proc is not None and self._sim_proc.poll() is None:
            self._sim_proc.terminate()
        self.destroy()


def show_path_tracking(parent, path_manager, map_data):
    if not path_manager or not path_manager.nodes:
        return
    dlg = PathTrackingDialog(parent, path_manager.nodes, map_data)
    dlg.wait_window()
