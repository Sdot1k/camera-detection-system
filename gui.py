import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
from PIL import Image, ImageTk
import cv2
import os
import csv
import subprocess
from datetime import datetime
from database import (
    get_devices, add_device, update_device, delete_device,
    get_detections, get_setting, set_setting, get_appdata_path,
    get_detections_filtered, get_detections_count, get_filtered_classes
)
from camera_manager import CameraThread, find_stream_url, get_screenshots_path
from detection import detect_objects, load_model

class CameraApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Camera Detection System")
        self.root.geometry("1200x800")
        icon_path = os.path.join(os.path.dirname(__file__), "ico.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)

        self.camera_threads = {}
        self.camera_frames = {}
        self.camera_images = {}
        self.enlarged_windows = {}
        self.enlarged_callbacks = {}

        style = ttk.Style()
        style.configure("Green.TLabel", foreground="green")
        style.configure("Red.TLabel", foreground="red")
        style.configure("Yellow.TLabel", foreground="orange")

        saved_theme = get_setting('theme') or 'vista'
        try:
            style.theme_use(saved_theme)
        except tk.TclError:
            style.theme_use('default')

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.frame_devices = ttk.Frame(self.notebook)
        self.frame_live = ttk.Frame(self.notebook)
        self.frame_logs = ttk.Frame(self.notebook)
        self.frame_settings = ttk.Frame(self.notebook)
        self.frame_photo = ttk.Frame(self.notebook)
        self.frame_help = ttk.Frame(self.notebook)

        self.notebook.add(self.frame_devices, text="Камеры")
        self.notebook.add(self.frame_live, text="Мониторинг")
        self.notebook.add(self.frame_photo, text="Фото")
        self.notebook.add(self.frame_logs, text="События")
        self.notebook.add(self.frame_settings, text="Настройки")
        self.notebook.add(self.frame_help, text="Справка")

        self.setup_devices_tab()
        self.setup_live_tab()
        self.setup_photo_tab()
        self.setup_logs_tab()
        self.setup_settings_tab()
        self.setup_help_tab()

        self.refresh_devices_list()
        self.refresh_camera_grid()

    def stop_all_threads(self):
        for thread in self.camera_threads.values():
            thread.stop()
        for thread in self.camera_threads.values():
            thread.join(timeout=1)
        self.camera_threads.clear()
        for win in self.enlarged_windows.values():
            win.destroy()
        self.enlarged_windows.clear()

    
    def setup_devices_tab(self):
        btn_frame = ttk.Frame(self.frame_devices)
        btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text="➕ Добавить камеру", command=self.add_device_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 Обновить список", command=self.refresh_devices_list).pack(side=tk.LEFT, padx=5)

        self.devices_tree = ttk.Treeview(self.frame_devices, columns=("id","name","type","url","active"), show="headings")
        self.devices_tree.heading("id", text="ID")
        self.devices_tree.heading("name", text="Название")
        self.devices_tree.heading("type", text="Тип")
        self.devices_tree.heading("url", text="URL")
        self.devices_tree.heading("active", text="Активна")
        self.devices_tree.column("id", width=50)
        self.devices_tree.column("name", width=150)
        self.devices_tree.column("type", width=80)
        self.devices_tree.column("url", width=300)
        self.devices_tree.column("active", width=80)
        self.devices_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        edit_frame = ttk.Frame(self.frame_devices)
        edit_frame.pack(pady=5)
        ttk.Button(edit_frame, text="✏️ Редактировать", command=self.edit_selected_device).pack(side=tk.LEFT, padx=5)
        ttk.Button(edit_frame, text="🗑️ Удалить", command=self.delete_selected_device).pack(side=tk.LEFT, padx=5)
        ttk.Button(edit_frame, text="🔘 Вкл/Выкл", command=self.toggle_selected_device).pack(side=tk.LEFT, padx=5)

    def refresh_devices_list(self):
        for item in self.devices_tree.get_children():
            self.devices_tree.delete(item)
        devices = get_devices()
        for dev in devices:
            active_str = "Да" if dev["is_active"] else "Нет"
            self.devices_tree.insert("", tk.END, values=(dev["id"], dev["name"], dev["type"], dev["url"] or "", active_str))

    def add_device_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Добавление устройства")
        dialog.geometry("500x650")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Название:").pack(pady=2)
        name_entry = tk.Entry(dialog, width=40)
        name_entry.pack(pady=2)

        tk.Label(dialog, text="Тип источника:").pack(pady=2)
        type_var = tk.StringVar(value="webcam")
        type_frame = ttk.Frame(dialog)
        ttk.Radiobutton(type_frame, text="Веб-камера", variable=type_var, value="webcam").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(type_frame, text="IP-камера (прямой URL)", variable=type_var, value="ip").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(type_frame, text="IP-камера (автопоиск)", variable=type_var, value="auto").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(type_frame, text="YouTube-камера", variable=type_var, value="youtube").pack(side=tk.LEFT, padx=5)
        type_frame.pack(pady=5)

        ip_frame = ttk.LabelFrame(dialog, text="Прямой URL")
        ip_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(ip_frame, text="URL (поток):").pack(pady=2)
        url_entry = tk.Entry(ip_frame, width=60)
        url_entry.pack(pady=2)
        tk.Label(ip_frame, text="Логин (опционально):").pack(pady=2)
        login_entry = tk.Entry(ip_frame, width=40)
        login_entry.pack(pady=2)
        tk.Label(ip_frame, text="Пароль:").pack(pady=2)
        pass_entry = tk.Entry(ip_frame, width=40, show="*")
        pass_entry.pack(pady=2)

        auto_frame = ttk.LabelFrame(dialog, text="Автопоиск (Hikvision, Dahua, Axis)")
        auto_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(auto_frame, text="IP адрес:").pack(pady=2)
        auto_ip_entry = tk.Entry(auto_frame, width=40)
        auto_ip_entry.pack(pady=2)
        tk.Label(auto_frame, text="Порт (обычно 80, 554, 8000):").pack(pady=2)
        auto_port_entry = tk.Entry(auto_frame, width=40)
        auto_port_entry.pack(pady=2)
        tk.Label(auto_frame, text="Логин:").pack(pady=2)
        auto_login_entry = tk.Entry(auto_frame, width=40)
        auto_login_entry.pack(pady=2)
        tk.Label(auto_frame, text="Пароль:").pack(pady=2)
        auto_pass_entry = tk.Entry(auto_frame, width=40, show="*")
        auto_pass_entry.pack(pady=2)
        auto_status = ttk.Label(auto_frame, text="", foreground="blue")
        auto_status.pack(pady=2)

        youtube_frame = ttk.LabelFrame(dialog, text="YouTube-камера")
        youtube_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(youtube_frame, text="URL YouTube:").pack(pady=2)
        youtube_url_entry = tk.Entry(youtube_frame, width=60)
        youtube_url_entry.pack(pady=2)

        ip_frame.pack_forget()
        auto_frame.pack_forget()
        youtube_frame.pack_forget()

        def on_type_change(*args):
            t = type_var.get()
            ip_frame.pack_forget()
            auto_frame.pack_forget()
            youtube_frame.pack_forget()
            if t == "ip":
                ip_frame.pack(fill=tk.X, padx=10, pady=5)
            elif t == "auto":
                auto_frame.pack(fill=tk.X, padx=10, pady=5)
            elif t == "youtube":
                youtube_frame.pack(fill=tk.X, padx=10, pady=5)
        type_var.trace('w', on_type_change)
        on_type_change()

        def on_save():
            name = name_entry.get().strip()
            if not name:
                messagebox.showerror("Ошибка", "Введите название")
                return
            dev_type = type_var.get()
            if dev_type == "webcam":
                add_device(name, "webcam")
                dialog.destroy()
                self.refresh_devices_list()
                self.refresh_camera_grid()
            elif dev_type == "ip":
                url = url_entry.get().strip()
                if not url:
                    messagebox.showerror("Ошибка", "Введите URL")
                    return
                username = login_entry.get().strip() or None
                password = pass_entry.get().strip() or None
                add_device(name, "ip", url, username, password)
                dialog.destroy()
                self.refresh_devices_list()
                self.refresh_camera_grid()
            elif dev_type == "auto":
                ip = auto_ip_entry.get().strip()
                port = auto_port_entry.get().strip()
                username = auto_login_entry.get().strip() or None
                password = auto_pass_entry.get().strip() or None
                if not ip:
                    messagebox.showerror("Ошибка", "Введите IP адрес")
                    return
                if not port:
                    port = "80"
                auto_status.config(text="Поиск потока...", foreground="blue")
                dialog.update()
                def search():
                    found = find_stream_url(ip, port, username, password, timeout=5)
                    if found:
                        add_device(name, "ip", found, username, password)
                        dialog.after(0, lambda: dialog.destroy())
                        self.refresh_devices_list()
                        self.refresh_camera_grid()
                    else:
                        dialog.after(0, lambda: auto_status.config(text="Не удалось найти поток. Проверьте данные.", foreground="red"))
                threading.Thread(target=search, daemon=True).start()
            elif dev_type == "youtube":
                url = youtube_url_entry.get().strip()
                if not url:
                    messagebox.showerror("Ошибка", "Введите URL YouTube")
                    return
                add_device(name, "youtube", url=url)
                dialog.destroy()
                self.refresh_devices_list()
                self.refresh_camera_grid()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Сохранить", command=on_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def test_selected_device(self):
        selected = self.devices_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите устройство")
            return
        item = self.devices_tree.item(selected[0])
        dev_id = item['values'][0]
        devices = get_devices()
        dev = next((d for d in devices if d["id"] == dev_id), None)
        if not dev:
            return
        def test():
            cap = None
            try:
                if dev["type"] == "webcam":
                    cap = cv2.VideoCapture(0)
                elif dev["type"] == "youtube":
                    from cap_from_youtube import cap_from_youtube
                    cap = cap_from_youtube(dev["url"], 'best')
                else:
                    url = dev["url"]
                    if dev["username"] and dev["password"]:
                        auth_url = f"rtsp://{dev['username']}:{dev['password']}@{url.split('://')[1] if '://' in url else url}"
                        cap = cv2.VideoCapture(auth_url)
                    else:
                        cap = cv2.VideoCapture(dev["url"])
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret:
                        messagebox.showinfo("Тест", "Камера работает")
                    else:
                        messagebox.showerror("Тест", "Камера открыта, но нет кадра")
                else:
                    messagebox.showerror("Тест", "Не удалось открыть камеру")
            except Exception as e:
                messagebox.showerror("Тест", str(e))
            finally:
                if cap:
                    cap.release()
        threading.Thread(target=test, daemon=True).start()

    def edit_selected_device(self):
        selected = self.devices_tree.selection()
        if not selected:
            return
        item = self.devices_tree.item(selected[0])
        dev_id = item['values'][0]
        devices = get_devices()
        dev = next((d for d in devices if d["id"] == dev_id), None)
        if not dev:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Редактирование устройства")
        dialog.geometry("400x350")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Название:").pack(pady=2)
        name_entry = tk.Entry(dialog, width=40)
        name_entry.insert(0, dev["name"])
        name_entry.pack(pady=2)

        tk.Label(dialog, text="URL:").pack(pady=2)
        url_entry = tk.Entry(dialog, width=60)
        url_entry.insert(0, dev["url"] or "")
        url_entry.pack(pady=2)

        tk.Label(dialog, text="Логин:").pack(pady=2)
        login_entry = tk.Entry(dialog, width=40)
        login_entry.insert(0, dev["username"] or "")
        login_entry.pack(pady=2)

        tk.Label(dialog, text="Пароль:").pack(pady=2)
        pass_entry = tk.Entry(dialog, width=40, show="*")
        pass_entry.insert(0, dev["password"] or "")
        pass_entry.pack(pady=2)

        def on_save():
            name = name_entry.get().strip()
            if not name:
                messagebox.showerror("Ошибка", "Введите название")
                return
            url = url_entry.get().strip()
            username = login_entry.get().strip() or None
            password = pass_entry.get().strip() or None
            update_device(dev_id, name=name, url=url, username=username, password=password)
            self.refresh_devices_list()
            self.refresh_camera_grid()
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Сохранить", command=on_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def delete_selected_device(self):
        selected = self.devices_tree.selection()
        if not selected:
            return
        item = self.devices_tree.item(selected[0])
        dev_id = item['values'][0]
        if messagebox.askyesno("Удаление", "Удалить устройство?"):
            if dev_id in self.camera_threads:
                self.camera_threads[dev_id].stop()
                self.camera_threads[dev_id].join(timeout=1)
                del self.camera_threads[dev_id]
            delete_device(dev_id)
            self.refresh_devices_list()
            self.refresh_camera_grid()

    def toggle_selected_device(self):
        selected = self.devices_tree.selection()
        if not selected:
            return
        item = self.devices_tree.item(selected[0])
        dev_id = item['values'][0]
        devices = get_devices()
        dev = next((d for d in devices if d["id"] == dev_id), None)
        if dev:
            new_active = not dev["is_active"]
            update_device(dev_id, is_active=new_active)
            self.refresh_devices_list()
            self.refresh_camera_grid()

    
    def setup_live_tab(self):
        self.grid_frame = ttk.Frame(self.frame_live)
        self.grid_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.canvas = tk.Canvas(self.grid_frame)
        self.scrollbar = ttk.Scrollbar(self.grid_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda e: self.refresh_camera_grid())

    def refresh_camera_grid(self):
        for dev_id, thread in list(self.camera_threads.items()):
            thread.stop()
            thread.join(timeout=1)
        self.camera_threads.clear()
        self.camera_frames.clear()
        self.camera_images.clear()
        for win in self.enlarged_windows.values():
            win.destroy()
        self.enlarged_windows.clear()
        self.enlarged_callbacks.clear()
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        devices = get_devices()
        active_devices = [d for d in devices if d["is_active"]]
        if not active_devices:
            label = ttk.Label(self.scrollable_frame, text="Нет активных камер. Добавьте и включите камеры.")
            label.pack(pady=20)
            return

        CAM_WIDTH = 320
        CAM_HEIGHT = 240
        PADDING = 10

        self.canvas.update_idletasks()
        canvas_width = self.canvas.winfo_width()
        if canvas_width < 100:
            canvas_width = 800
        cols = max(1, canvas_width // (CAM_WIDTH + PADDING))
        cols = min(cols, 6)

        rows = (len(active_devices) + cols - 1) // cols

        for idx, dev in enumerate(active_devices):
            row = idx // cols
            col = idx % cols
            frame = ttk.LabelFrame(self.scrollable_frame, text=dev["name"], relief=tk.RIDGE)
            frame.grid(row=row, column=col, padx=PADDING//2, pady=PADDING//2, sticky="nw")
            frame.grid_propagate(False)
            frame.config(width=CAM_WIDTH + PADDING, height=CAM_HEIGHT + 35)
            label = tk.Label(frame, width=CAM_WIDTH, height=CAM_HEIGHT, relief=tk.SUNKEN, bg="black")
            label.pack(fill=tk.BOTH, expand=True)
            self.camera_frames[dev["id"]] = label
            label.bind("<Double-Button-1>", lambda e, d=dev: self.enlarge_camera(d["id"]))

            status_label = ttk.Label(frame, text="🟡", style="Yellow.TLabel")
            status_label.place(x=5, y=5)

            def status_callback(dev_id, status, dev_name=dev["name"]):
                for w in self.scrollable_frame.winfo_children():
                    if isinstance(w, ttk.LabelFrame) and w.cget("text") == dev_name:
                        for child in w.winfo_children():
                            if isinstance(child, ttk.Label) and child.cget("text") in ["🟢", "🟡", "🔴"]:
                                if status == "active":
                                    child.config(text="🟢", style="Green.TLabel")
                                elif status == "connecting":
                                    child.config(text="🟡", style="Yellow.TLabel")
                                else:
                                    child.config(text="🔴", style="Red.TLabel")
                                break
                        break

            thread = CameraThread(dev)
            thread.register_callback(self.update_grid_image)
            thread.set_status_callback(status_callback)
            thread.start()
            self.camera_threads[dev["id"]] = thread

        for i in range(rows):
            self.scrollable_frame.grid_rowconfigure(i, weight=0)
        for i in range(cols):
            self.scrollable_frame.grid_columnconfigure(i, weight=0)

        self.scrollable_frame.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def update_grid_image(self, device_id, frame):
        if device_id not in self.camera_frames:
            return
        label = self.camera_frames[device_id]
        try:
            if not label.winfo_exists():
                return
        except:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        width = label.winfo_width()
        height = label.winfo_height()
        if width > 10 and height > 10:
            img = img.resize((width, height), Image.Resampling.LANCZOS)
        imgtk = ImageTk.PhotoImage(image=img)
        self.camera_images[device_id] = imgtk
        self.root.after(0, lambda: label.config(image=imgtk) if label.winfo_exists() else None)

    def enlarge_camera(self, device_id):
        if device_id not in self.camera_threads:
            messagebox.showerror("Ошибка", "Камера не активна или не найдена")
            return
        if device_id in self.enlarged_windows and self.enlarged_windows[device_id].winfo_exists():
            self.enlarged_windows[device_id].lift()
            return

        win = tk.Toplevel(self.root)
        win.title(f"Увеличенный вид - {self.get_device_name(device_id)}")
        win.geometry("800x600")
        win.minsize(400, 300)
        win.protocol("WM_DELETE_WINDOW", lambda: self.close_enlarged_window(device_id))
        icon_path = os.path.join(os.path.dirname(__file__), "ico.ico")
        if os.path.exists(icon_path):
            win.iconbitmap(icon_path)

        label = tk.Label(win, bg="black")
        label.pack(fill=tk.BOTH, expand=True)

        win._target_size = (800, 600)

        def update_size():
            if not win.winfo_exists():
                return
            w = label.winfo_width()
            h = label.winfo_height()
            if w > 10 and h > 10:
                win._target_size = (w, h)

        def on_resize(event=None):
            if hasattr(win, '_resize_timer'):
                win.after_cancel(win._resize_timer)
            win._resize_timer = win.after(150, update_size)

        win.bind("<Configure>", on_resize)

        def update_enlarged(dev_id, frame):
            if dev_id != device_id:
                return
            try:
                if not win.winfo_exists():
                    return
                target_w, target_h = win._target_size
                if target_w <= 10 or target_h <= 10:
                    win.update_idletasks()
                    target_w = max(100, label.winfo_width())
                    target_h = max(100, label.winfo_height())
                    if target_w <= 10:
                        target_w, target_h = 800, 600
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
                img_w, img_h = img.size
                scale = min(target_w / img_w, target_h / img_h)
                new_w = int(img_w * scale)
                new_h = int(img_h * scale)
                if new_w > 0 and new_h > 0:
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    imgtk = ImageTk.PhotoImage(image=img)
                    label.config(image=imgtk)
                    win.current_img = imgtk
            except Exception as e:
                print(f"Ошибка обновления увеличенного окна: {e}")

        self.camera_threads[device_id].register_callback(update_enlarged)
        self.enlarged_windows[device_id] = win
        self.enlarged_callbacks[device_id] = update_enlarged
        win.after(200, update_size)
        win.focus_force()
        win.lift()

    def close_enlarged_window(self, device_id):
        if device_id in self.enlarged_windows:
            win = self.enlarged_windows[device_id]
            win.destroy()
            del self.enlarged_windows[device_id]
        if device_id in self.enlarged_callbacks and device_id in self.camera_threads:
            self.camera_threads[device_id].unregister_callback(self.enlarged_callbacks[device_id])
            del self.enlarged_callbacks[device_id]

    def get_device_name(self, device_id):
        devices = get_devices()
        dev = next((d for d in devices if d["id"] == device_id), None)
        return dev["name"] if dev else "Камера"

    
    def setup_photo_tab(self):
        top_frame = ttk.Frame(self.frame_photo)
        top_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(top_frame, text="Загрузить изображение", command=self.load_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="Распознать объекты", command=self.detect_on_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="Сохранить результат", command=self.save_result_image).pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(top_frame, text="")
        self.status_label.pack(side=tk.LEFT, padx=20)

        self.image_frame = ttk.Frame(self.frame_photo)
        self.image_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.image_label = tk.Label(self.image_frame, bg="gray", relief=tk.SUNKEN)
        self.image_label.pack(fill=tk.BOTH, expand=True)

        self.current_image = None
        self.current_display = None
        self.result_image = None

    def load_image(self):
        filetypes = [("Изображения", "*.jpg *.jpeg *.png *.bmp"), ("Все файлы", "*.*")]
        filename = filedialog.askopenfilename(title="Выберите изображение", filetypes=filetypes)
        if not filename:
            return
        self.current_image = cv2.imread(filename)
        if self.current_image is None:
            messagebox.showerror("Ошибка", "Не удалось загрузить изображение")
            return
        self.result_image = self.current_image.copy()
        self.display_image(self.result_image)
        self.status_label.config(text="Изображение загружено. Нажмите 'Распознать объекты'")

    def display_image(self, img_np):
        h, w = img_np.shape[:2]
        max_width = self.image_label.winfo_width() if self.image_label.winfo_width() > 100 else 800
        max_height = self.image_label.winfo_height() if self.image_label.winfo_height() > 100 else 600
        scale = min(max_width / w, max_height / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(img_np, (new_w, new_h))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        imgtk = ImageTk.PhotoImage(image=img)
        self.current_display = imgtk
        self.image_label.config(image=imgtk)

    def detect_on_image(self):
        if self.current_image is None:
            messagebox.showwarning("Внимание", "Сначала загрузите изображение")
            return
        try:
            model = load_model()
            conf_threshold = float(get_setting('confidence'))
            filtered_classes = get_filtered_classes()
            detections = detect_objects(self.current_image)
            self.result_image = self.current_image.copy()
            detected_info = []
            for (x1, y1, x2, y2, class_name, conf) in detections:
                if filtered_classes is not None and class_name.lower() not in filtered_classes:
                    continue
                cv2.rectangle(self.result_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = f"{class_name} {conf:.2f}"
                cv2.putText(self.result_image, label, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
                detected_info.append(f"{class_name} ({conf:.2f})")
            self.display_image(self.result_image)
            if detected_info:
                self.status_label.config(text=f"Обнаружено: {', '.join(detected_info)}")
            else:
                self.status_label.config(text="Объекты не обнаружены")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при распознавании: {e}")

    def save_result_image(self):
        if self.result_image is None:
            messagebox.showwarning("Внимание", "Нет результата для сохранения")
            return
        filetypes = [("JPEG", "*.jpg"), ("PNG", "*.png"), ("Все файлы", "*.*")]
        filename = filedialog.asksaveasfilename(defaultextension=".jpg", filetypes=filetypes)
        if filename:
            cv2.imwrite(filename, self.result_image)
            self.status_label.config(text=f"Сохранено: {filename}")

    
    def setup_logs_tab(self):
        top_frame = ttk.Frame(self.frame_logs)
        top_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(top_frame, text="Обновить", command=self.refresh_logs).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="Экспорт в CSV", command=self.export_logs_csv).pack(side=tk.LEFT, padx=5)

        self.logs_tree = ttk.Treeview(self.frame_logs, columns=("num","type","timestamp","dev_id"), show="headings")
        self.logs_tree.heading("num", text="№ (по типу)")
        self.logs_tree.heading("type", text="Тип объекта")
        self.logs_tree.heading("timestamp", text="Дата/время")
        self.logs_tree.heading("dev_id", text="ID камеры")
        self.logs_tree.column("num", width=100)
        self.logs_tree.column("type", width=150)
        self.logs_tree.column("timestamp", width=180)
        self.logs_tree.column("dev_id", width=80)
        self.logs_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.refresh_logs()
        self.auto_refresh_logs()

    def auto_refresh_logs(self):
        self.refresh_logs()
        self.root.after(3000, self.auto_refresh_logs)

    def refresh_logs(self):
        for item in self.logs_tree.get_children():
            self.logs_tree.delete(item)
        logs = get_detections(limit=200)
        for log in logs:
            self.logs_tree.insert("", tk.END, values=(log["detection_number"], log["object_type"], log["timestamp"], log["device_id"] or ""))

    def export_logs_csv(self):
        logs = get_detections(limit=10000)
        if not logs:
            messagebox.showinfo("Экспорт", "Нет данных для экспорта")
            return
        filename = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if filename:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["ID", "№ по типу", "Тип объекта", "Дата/время", "ID камеры"])
                for log in logs:
                    writer.writerow([log["id"], log["detection_number"], log["object_type"], log["timestamp"], log["device_id"]])
            messagebox.showinfo("Экспорт", f"Логи сохранены в {filename}")

    
    def setup_settings_tab(self):
        settings_frame = ttk.LabelFrame(self.frame_settings, text="Внешний вид")
        settings_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(settings_frame, text="Тема:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.theme_var = tk.StringVar(value=get_setting('theme') or 'vista')
        theme_combo = ttk.Combobox(settings_frame, textvariable=self.theme_var, values=['vista', 'default', 'alt', 'clam'], state='readonly')
        theme_combo.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(settings_frame, text="Применить", command=self.change_theme).grid(row=0, column=2, padx=5)

        ttk.Button(settings_frame, text="Открыть папку со скриншотами", command=self.open_screenshots_folder).grid(row=1, column=0, columnspan=3, pady=5)

        frame = ttk.LabelFrame(self.frame_settings, text="Параметры детекции")
        frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(frame, text="Тип модели:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.model_type_var = tk.StringVar(value=get_setting('model_type'))
        model_type_combo = ttk.Combobox(frame, textvariable=self.model_type_var, values=['pt', 'onnx'], state='readonly')
        model_type_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(frame, text="Путь к модели:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.model_path_var = tk.StringVar(value=get_setting('model_path') or '')
        model_path_entry = ttk.Entry(frame, textvariable=self.model_path_var, width=40)
        model_path_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(frame, text="Выбрать модель", command=self.browse_model_file).grid(row=1, column=2, padx=5)

        ttk.Label(frame, text="Порог уверенности (0-1):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.conf_var = tk.DoubleVar(value=float(get_setting('confidence')))
        conf_scale = ttk.Scale(frame, from_=0.0, to=1.0, variable=self.conf_var, orient=tk.HORIZONTAL, length=200)
        conf_scale.grid(row=2, column=1, padx=5, pady=5)
        self.conf_label = ttk.Label(frame, text=f"{self.conf_var.get():.2f}")
        self.conf_label.grid(row=2, column=2, padx=5)
        conf_scale.configure(command=lambda v: self.conf_label.configure(text=f"{float(v):.2f}"))

        ttk.Label(frame, text="Детекция каждые N кадров:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.detect_every_var = tk.IntVar(value=int(get_setting('detect_every_n_frames')))
        detect_spin = ttk.Spinbox(frame, from_=1, to=10, textvariable=self.detect_every_var, width=5)
        detect_spin.grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(frame, text="Фильтр классов (через запятую):").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        self.filter_classes_var = tk.StringVar(value=get_setting('filtered_classes') or '')
        filter_entry = ttk.Entry(frame, textvariable=self.filter_classes_var, width=30)
        filter_entry.grid(row=4, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Label(frame, text="Оставьте пустым для всех классов", foreground="gray").grid(row=4, column=2, sticky=tk.W, padx=5)

        def show_available_classes():
            try:
                from detection import get_model_classes
                classes = get_model_classes()
                messagebox.showinfo("Доступные классы", ", ".join(classes))
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось загрузить модель: {e}")
        ttk.Button(frame, text="Показать доступные классы", command=show_available_classes).grid(row=5, column=0, columnspan=3, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=6, column=0, columnspan=3, pady=10)
        ttk.Button(btn_frame, text="Сохранить настройки", command=self.save_settings).pack(side=tk.LEFT, padx=5)

    def browse_model_file(self):
        filename = filedialog.askopenfilename(
            title="Выберите файл модели",
            filetypes=[("Модели YOLO", "*.pt *.onnx"), ("Все файлы", "*.*")]
        )
        if filename:
            self.model_path_var.set(filename)

    def change_theme(self):
        theme = self.theme_var.get()
        try:
            style = ttk.Style()
            style.theme_use(theme)
            set_setting('theme', theme)
        except tk.TclError:
            messagebox.showerror("Ошибка", f"Тема '{theme}' недоступна в вашей системе")

    def open_screenshots_folder(self):
        screens_dir = get_screenshots_path()
        if os.name == 'nt':
            os.startfile(screens_dir)
        else:
            subprocess.Popen(['xdg-open', screens_dir])

    def save_settings(self):
        set_setting('model_type', self.model_type_var.get())
        set_setting('model_path', self.model_path_var.get())
        set_setting('confidence', self.conf_var.get())
        set_setting('detect_every_n_frames', self.detect_every_var.get())
        set_setting('filtered_classes', self.filter_classes_var.get())
        messagebox.showinfo("Настройки", "Настройки сохранены. Перезапустите потоки камер для применения.")
        self.refresh_camera_grid()

 
    def setup_help_tab(self):
        text = tk.Text(self.frame_help, wrap=tk.WORD, font=("Arial", 10))
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        scrollbar = ttk.Scrollbar(text, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        help_content = """
Camera Detection System – инструкция по использованию

1. Управление камерами
   - Добавление: выберите тип (веб-камера / IP-камера / автопоиск / YouTube-камера), введите данные.
   - Тест: проверяет, доступна ли камера.
   - Редактирование: изменить параметры.
   - Вкл/Выкл: временно отключить камеру.

2. Прямая трансляция
   - Активные камеры отображаются в виде сетки.
   - Двойной клик по видео – увеличенный вид.
   - Зелёные рамки – обнаруженные объекты с подписью.
   - FPS и дата/время отображаются на видео.

3. Фото
   - Загрузите изображение, нажмите "Распознать объекты".
   - Результат можно сохранить.

4. События
   - Все обнаружения сохраняются в базе данных.
   - Можно экспортировать в CSV.

5. Настройки
   - Тема: изменить внешний вид.
   - Модель: выбрать файл .pt или .onnx.
   - Порог уверенности, частота детекции, фильтр классов.
   - Открыть папку со скриншотами.

6. Скриншоты
   - Сохраняются автоматически при обнаружении нового объекта.


"""
        text.insert(tk.END, help_content)
        text.configure(state=tk.DISABLED)

    def on_closing(self):
        self.stop_all_threads()
        self.root.destroy()