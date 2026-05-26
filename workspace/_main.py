"""Фиббоначи калькулятор с графическим интерфейсом tkinter"""

import tkinter as tk
from tkinter import ttk


class FibonacciGUI:
    """Фиббоначи калькулятор с графическим интерфейсом"""

    def __init__(self):
        """Инициализация GUI приложения"""
        self.root = None
        self.label_num_terms = None
        self.spinbox_num = None
        self.result_text = None

    def create_window(self):
        """Создание главного окна"""
        self.root = tk.Tk()
        self.root.title("Калькуlator Фиббоначи")
        self.root.geometry("500x300")
        self.root.resizable(True, True)

    def create_labels(self):
        """Создание меток для интерфейса"""
        # Метка для количества элементов
        self.label_num_terms = ttk.Label(
            self.root,
            text="Количество цифр Фиббоначи:",
            font=("Arial", 12)
        )

        # Метка для результата
        self.result_label = ttk.Label(
            self.root,
            text="Результат:",
            font=("Arial", 12)
        )

    def create_textboxes(self):
        """Создание текстовых областей (если нужно)"""
        # Текстовая область для вывода последовательности
        self.result_text = tk.Text(
            self.root,
            height=6,
            width=50,
            font=("Courier", 10),
            bg="#f0f0f0"
        )

    def create_button_calc(self):
        """Создание кнопки расчета"""
        self.calc_btn = ttk.Button(
            self.root,
            text="Рассчитать последовательность",
            command=self.calculate_fibonacci
        )

    def calculate_fibonacci(self):
        """Расчет последовательности Фиббоначи и вывод результата"""
        try:
            num_terms = int(self.spinbox_num.get())

            if num_terms < 1:
                self.result_text.delete(1.0, tk.END)
                self.result_text.insert(tk.END, "Количество должно быть >= 1")
                return

            if num_terms < 3:
                fib_seq = [num_terms] * num_terms
            else:
                fib_seq = [0, 1]
                for i in range(2, num_terms):
                    next_num = fib_seq[i - 1] + fib_seq[i - 2]
                    fib_seq.append(next_num)

            # Форматированный вывод с разделителями по 5 элементов
            formatted_result = ", ".join(str(n) for n in fib_seq[:45])
            if len(fib_seq) > 45:
                formatted_result += f", ... и ещё {len(fib_seq) - 45} значений"

            self.result_text.insert(tk.END, formatted_result)
            self.last_result = ", ".join(str(n) for n in fib_seq)

        except ValueError:
            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, "Ошибка! Введите целое число")
        except Exception as e:
            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, f"Ошибка: {str(e)}")

    def create_button_clear(self):
        """Создание кнопки очистки"""
        self.clear_btn = ttk.Button(
            self.root,
            text="Очистить",
            command=self.clear_all
        )

    def clear_all(self):
        """Очистка всех полей и результата"""
        try:
            num_terms_str = tk.StringVar()
        except:
            pass
        if hasattr(self, 'spinbox_num') and self.spinbox_num:
            self.spinbox_num.delete(0, tk.END)
        if hasattr(self, 'result_text'):
            self.result_text.delete(1.0, tk.END)

    def create_spinbox_num(self):
        """Создание spinbox для выбора количества элементов"""
        # Переменная для хранения значения spinbox
        num_terms_var = tk.StringVar()

        self.spinbox_num = ttk.Spinbox(
            self.root,
            from_=1,
            to=100,  # Максимум 100 элементов
            textcommand=self.recalc_on_change
        )

    def recalc_on_change(self, *args):
        """Пересчет при изменении значения spinbox"""
        try:
            num_terms = int(self.spinbox_num.get())
            # Можно автоматически рассчитать или просто обновить значение
            if hasattr(self, 'last_result') and self.last_result:
                self.result_text.delete(1.0, tk.END)
                self.result_text.insert(tk.END, f"Всего элементов: {num_terms}")
        except ValueError:
            pass

    def pack_widgets(self):
        """Размещение виджетов на окне"""
        # Отступ сверху
        pady = 10
        padx = 20

        # Метка количества и spinbox на одной строке
        row_frame = ttk.Frame(self.root)
        row_frame.pack(pady=25, fill='x')

        ttk.Label(row_frame, text="Количество:", font=("Arial", 12)).pack(side='left', padx=5)
        self.spinbox_num.pack(side='left', padx=5, ipadx=5)

        # Кнопка расчета
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(pady=15, fill='x')
        self.calc_btn.pack(side='left', padx=10)
        self.clear_btn.pack(side='right', padx=10)

        # Область результата
        result_frame = ttk.Frame(self.root)
        result_frame.pack(pady=(20, 10), fill='both', expand=True)
        self.result_text.pack(fill='both', expand=True, padx=10, pady=5)

        # Заголовок результата
        if hasattr(self, 'result_label'):
            self.result_label.pack(pady=5)

    def destroy_window(self):
        """Уничтожение окна и выход из программы"""
        if self.root:
            self.root.destroy()


def run_gui_app():
    """Запуск GUI приложения"""
    app = FibonacciGUI()
    
    # Создание компонентов
    app.create_window()
    app.create_labels()
    app.create_spinbox_num()
    app.create_textboxes()

    # Настройка spinbox для пересчета при изменении (опционально)
    if hasattr(app, 'spinbox_num'):
        app.spinbox_num.delete(0, tk.END)
        app.spinbox_num.insert(0, 15)

    # Создание кнопок
    app.create_button_calc()
    app.create_button_clear()

    # Размещение виджетов
    app.pack_widgets()

    # Запуск главного цикла
    app.root.mainloop()


if __name__ == "__main__":
    run_gui_app()
