import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import json
import ctypes
from ctypes import wintypes
import queue
from pynput import keyboard

# ================= 配置与常量 =================
APP_NAME = "映射工具"
VERSION = "v4.0.0 (王于兴师瞎搞版)"

# Windows API 常量
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# 定义 C 结构体用于获取当前鼠标位置
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

# ================= 核心工具类：幽灵点击器 (Ghost Clicker) =================

class GhostClicker:
    """
    解决后台消息被游戏忽略坐标的问题。
    采用 '瞬移-点击-归位' 策略，速度极快，肉眼几乎不可见。
    """
    def __init__(self):
        self.user32 = ctypes.windll.user32

    def click(self, target_x, target_y, double=False):
        try:
            # 1. 保存当前鼠标位置
            current_pos = POINT()
            self.user32.GetCursorPos(ctypes.byref(current_pos))
            old_x, old_y = current_pos.x, current_pos.y

            # 2. 瞬间移动到目标位置
            self.user32.SetCursorPos(target_x, target_y)

            # 3. 执行点击 (物理级模拟)
            self.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            # 稍微一点点延迟确保游戏接收到
            time.sleep(0.005) 
            self.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

            if double:
                time.sleep(0.05)
                self.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                time.sleep(0.005)
                self.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

            # 4. 瞬间移回原位
            self.user32.SetCursorPos(old_x, old_y)
                
        except Exception as e:
            print(f"点击异常: {e}")

# ================= 界面辅助类 =================

class SelectionOverlay(tk.Toplevel):
    """全屏选区工具"""
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.callback = callback
        self.attributes('-alpha', 0.3)
        self.attributes('-fullscreen', True)
        self.attributes('-topmost', True)
        self.configure(bg='black')
        self.overrideredirect(True)
        
        self.canvas = tk.Canvas(self, cursor="cross", bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.start_x = None
        self.start_y = None
        self.rect = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_force()

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', width=2, fill='white')

    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        end_x, end_y = event.x, event.y
        center_x = (self.start_x + end_x) // 2
        center_y = (self.start_y + end_y) // 2
        self.destroy()
        self.callback(center_x, center_y)

class VisualFeedback(tk.Toplevel):
    """视觉反馈"""
    def __init__(self, x, y):
        super().__init__()
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.attributes('-alpha', 0.8)
        self.attributes('-transparentcolor', 'white')
        
        size = 40
        x_pos = x - size // 2
        y_pos = y - size // 2
        self.geometry(f"{size}x{size}+{x_pos}+{y_pos}")
        
        canvas = tk.Canvas(self, bg='white', highlightthickness=0)
        canvas.pack(fill='both', expand=True)
        canvas.create_oval(2, 2, size-2, size-2, outline='#00FF00', width=3)
        
        self.after(150, self.destroy)

# ================= 主程序 =================

class TouchSimulatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {VERSION}")
        self.root.geometry("900x600")
        
        # 使用修复后的点击器
        self.clicker = GhostClicker()
        self.listener = None
        self.is_listening = False
        self.bindings = []
        
        self.ui_queue = queue.Queue()
        self.setup_ui()
        self.check_queue()

    def setup_ui(self):
        style = ttk.Style()
        style.configure("Treeview", rowheight=25)
        style.configure("Bold.TButton", font=('Segoe UI', 9, 'bold'))
        
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill="x")
        
        self.btn_listen = ttk.Button(top_frame, text="▶ 开启辅助", command=self.toggle_listening, style="Bold.TButton")
        self.btn_listen.pack(side="left", padx=5)
        
        ttk.Button(top_frame, text="+ 添加点击位", command=self.add_binding_dialog).pack(side="left", padx=5)
        ttk.Button(top_frame, text="导入配置", command=self.import_config).pack(side="right", padx=5)
        ttk.Button(top_frame, text="导出配置", command=self.export_config).pack(side="right", padx=5)
        
        self.lbl_status = ttk.Label(top_frame, text="状态: 已停止", foreground="red")
        self.lbl_status.pack(side="left", padx=20)

        list_frame = ttk.Frame(self.root, padding=10)
        list_frame.pack(fill="both", expand=True)
        
        columns = ("name", "key", "coords", "delay", "count", "status")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        
        self.tree.heading("name", text="名称")
        self.tree.heading("key", text="按键")
        self.tree.heading("coords", text="坐标")
        self.tree.heading("delay", text="延迟")
        self.tree.heading("count", text="次数")
        self.tree.heading("status", text="状态")
        
        self.tree.column("name", width=150)
        self.tree.column("key", width=100)
        self.tree.column("coords", width=120)
        self.tree.column("delay", width=80)
        self.tree.column("count", width=80)
        self.tree.column("status", width=60)
        
        self.tree.pack(side="left", fill="both", expand=True)
        
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="删除", command=self.delete_binding)
        self.context_menu.add_command(label="重置计数", command=self.reset_count)
        self.tree.bind("<Button-3>", self.show_context_menu)

        bottom_frame = ttk.Frame(self.root, padding=5)
        bottom_frame.pack(fill="x", side="bottom")
        ttk.Label(bottom_frame, text="修复说明: 采用'极速归位'技术，解决游戏忽略坐标问题").pack(side="left")

    def check_queue(self):
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                if msg['type'] == 'update_count':
                    self.update_tree_count(msg['index'], msg['count'])
                elif msg['type'] == 'feedback':
                    VisualFeedback(msg['x'], msg['y'])
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self.check_queue)

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def add_binding_dialog(self):
        messagebox.showinfo("提示", "点击确定后，框选游戏按钮区域。\n程序将自动记录坐标。")
        self.root.iconify()
        time.sleep(0.2)
        SelectionOverlay(self.root, self.on_area_selected)

    def on_area_selected(self, x, y):
        self.root.deiconify()
        self.show_binding_form(x, y)

    def show_binding_form(self, x, y):
        dlg = tk.Toplevel(self.root)
        dlg.title("配置")
        dlg.geometry("300x350")
        dlg.transient(self.root)
        dlg.grab_set()
        
        ttk.Label(dlg, text="名称:").pack(anchor="w", padx=10, pady=5)
        entry_name = ttk.Entry(dlg)
        entry_name.pack(fill="x", padx=10)
        
        ttk.Label(dlg, text="按键:").pack(anchor="w", padx=10, pady=5)
        entry_key = ttk.Entry(dlg)
        entry_key.pack(fill="x", padx=10)
        
        def on_key_capture(event):
            key_name = event.keysym.upper()
            if len(key_name) == 1: key_name = key_name.upper()
            entry_key.delete(0, tk.END)
            entry_key.insert(0, key_name)
            return "break"
        entry_key.bind("<KeyPress>", on_key_capture)
        
        ttk.Label(dlg, text="延迟(ms):").pack(anchor="w", padx=10, pady=5)
        scale = tk.Scale(dlg, from_=0, to=500, orient="horizontal")
        scale.set(10)
        scale.pack(fill="x", padx=10)
        
        def confirm():
            if entry_name.get() and entry_key.get():
                self.bindings.append({
                    "name": entry_name.get(), "key": entry_key.get(),
                    "x": x, "y": y, "delay": scale.get(),
                    "count": 0, "status": "启用"
                })
                self.refresh_list()
                dlg.destroy()
        ttk.Button(dlg, text="确定", command=confirm).pack(pady=20)

    def refresh_list(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        for idx, b in enumerate(self.bindings):
            self.tree.insert("", "end", iid=idx, values=(
                b['name'], b['key'], f"{b['x']}, {b['y']}", 
                f"{b['delay']} ms", b['count'], b['status']
            ))

    def update_tree_count(self, index, count):
        if self.tree.exists(index):
            curr = list(self.tree.item(index, "values"))
            curr[4] = count
            self.tree.item(index, values=curr)

    def delete_binding(self):
        sel = self.tree.selection()
        if sel:
            del self.bindings[int(sel[0])]
            self.refresh_list()

    def reset_count(self):
        sel = self.tree.selection()
        if sel:
            self.bindings[int(sel[0])]['count'] = 0
            self.refresh_list()

    def toggle_listening(self):
        if self.is_listening: self.stop_listening()
        else: self.start_listening()

    def start_listening(self):
        self.is_listening = True
        self.btn_listen.configure(text="■ 停止辅助")
        self.lbl_status.configure(text="状态: 运行中", foreground="green")
        self.listener = keyboard.Listener(on_press=self.on_key_press)
        self.listener.start()

    def stop_listening(self):
        self.is_listening = False
        self.btn_listen.configure(text="▶ 开启辅助")
        self.lbl_status.configure(text="状态: 已停止", foreground="red")
        if self.listener:
            self.listener.stop()
            self.listener = None

    def on_key_press(self, key):
        if not self.is_listening: return
        try: k = key.char.upper() if hasattr(key, 'char') else key.name.upper()
        except: return
        for idx, b in enumerate(self.bindings):
            if b['key'] == k and b['status'] == "启用":
                threading.Thread(target=self.execute_action, args=(idx, b)).start()

    def execute_action(self, idx, binding):
        if binding['delay'] > 0: time.sleep(binding['delay'] / 1000.0)
        # 执行极速归位点击
        self.clicker.click(binding['x'], binding['y'])
        
        self.bindings[idx]['count'] += 1
        self.ui_queue.put({'type': 'update_count', 'index': idx, 'count': self.bindings[idx]['count']})
        self.ui_queue.put({'type': 'feedback', 'x': binding['x'], 'y': binding['y']})

    def export_config(self):
        f = filedialog.asksaveasfilename(defaultextension=".json")
        if f:
            with open(f, 'w') as file: json.dump(self.bindings, file)

    def import_config(self):
        f = filedialog.askopenfilename()
        if f:
            with open(f, 'r') as file:
                self.bindings = json.load(file)
            self.refresh_list()

if __name__ == "__main__":
    try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    root = tk.Tk()
    app = TouchSimulatorApp(root)
    root.mainloop()