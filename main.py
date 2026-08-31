import tkinter as tk
from tkinter import filedialog, messagebox
from database import init_db, get_setting, set_setting
from gui import CameraApp
import os

def main():
    init_db()
    root = tk.Tk()
    root.withdraw()

    model_path = get_setting('model_path')
    if not model_path or not os.path.exists(model_path):
        msg = ("Модель не найдена. Пожалуйста, выберите файл модели (.pt или .onnx).\n"
               "Вы можете скачать стандартную модель yolov8n.pt с GitHub или использовать свою.")
        messagebox.showinfo("Выбор модели", msg)
        filetypes = [("Модели YOLO", "*.pt *.onnx"), ("Все файлы", "*.*")]
        new_path = filedialog.askopenfilename(title="Выберите файл модели", filetypes=filetypes)
        if not new_path:
            messagebox.showerror("Ошибка", "Модель не выбрана. Программа будет закрыта.")
            return
        ext = os.path.splitext(new_path)[1].lower()
        if ext == '.pt':
            set_setting('model_type', 'pt')
        elif ext == '.onnx':
            set_setting('model_type', 'onnx')
        else:
            messagebox.showerror("Ошибка", "Неподдерживаемый формат модели. Выберите .pt или .onnx")
            return
        set_setting('model_path', new_path)

    root.deiconify()
    if os.path.exists("ico.ico"):
        root.iconbitmap("ico.ico")
    app = CameraApp(root)

    def on_closing():
        app.stop_all_threads()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()