'''Модуль для графического интерфейса Python-калькулятора фиббоначи.'''

import tkinter as tk
from tkinter import ttk, scrolledtext


class FibonacciGUI:
    """Фиббоначи калькулятор с графическим интерфейсом"""

    def __init__(self):
        self.root = None  # Основное окно приложения
        self.label_result = None  # Метка для результатов
        self.textbox_output = None  # Текстовый вывод
        self.button_calc = None  # Кнопка расчета
        self.button_clear = None  # Кнопка очистки
        self.spinbox_num = None  # Спинбокс для количества чисел

    def create_window(self):
        """Создание основного окна приложения"""
        self.root = tk.Tk()
        self.root.title("Калькулятор Фиббоначи")
        self.root.geometry("500x300")
        
    def create_labels(self):
        """Создание меток для интерфейса"""
        self.label_title = tk.Label(
            self.root,
            text="Фиббоначи Калькулятор",
            font=("Arial", 16, "bold")
        )
        self.label_title.pack(pady=10)

    def create_textboxes(self):
        """Создание текстовых полей для вывода"""
        frame_output = tk.Frame(self.root)
        frame_output.pack(padx=10, pady=5)
        
        self.label_result = tk.Label(
            frame_output,
            text="Результат:",
            font=("Arial", 10),
            anchor="w"
        )
        self.label_result.pack(fill=tk.X)

    def create_button_calc(self):
        """Создание кнопки расчета"""
        frame_buttons = tk.Frame(self.root)
        frame_buttons.pack(pady=5)
        
        self.button_calc = ttk.Button(
            frame_buttons,
            text="Рассчитать",
            command=self.calculate_fibonacci
        )
        self.button_calc.pack(side=tk.LEFT, padx=10)

    def create_button_clear(self):
        """Создание кнопки очистки"""
        self.button_clear = ttk.Button(
            frame_buttons,
            text="Очистить",
            command=self.clear_output
        )
        self.button_clear.pack(side=tk.LEFT, padx=10)

    def create_spinbox_num(self):
        """Создание спинбокса для количества чисел фиббоначи"""
        frame_spin = tk.Frame(self.root)
        frame_spin.pack(pady=5)
        
        self.label_count = tk.Label(
            frame_spin,
            text="Количество чисел:",
            font=("Arial", 10)
        )
        self.label_count.pack(side=tk.LEFT, padx=(0, 10))

    def pack_widgets(self):
        """Упаковка всех виджетов"""
        self.create_window()
        self.create_labels()
        self.create_textboxes()
        self.create_spinbox_num()
        self.create_button_calc()
        self.create_button_clear()
        
        # Создаем дефолтные значения для спинбокса
        frame_spin = tk.Frame(self.root)
        frame_spin.pack(pady=5, fill=tk.X)
        
        self.spinbox_num = ttk.Spinbox(
            frame_spin,
            from_=1,
            to=100,
            increment=1,
            width=8,
            command=self.calculate_fibonacci
        )
        self.spinbox_num.insert(0, 10)
        self.spinbox_num.pack(side=tk.LEFT)
        
        # Блокируем спинбокс по умолчанию (меняется только кнопкой расчета)
        self.spinbox_num.configure(state='readonly')

    def calculate_fibonacci(self):
        """Расчет последовательности Фиббоначи"""
        try:
            n = int(self.spinbox_num.get())
            
            fib_sequence = []
            a, b = 0, 1
            
            for _ in range(n):
                fib_sequence.append(a)
                a, b = b, a + b
            
            result_text = ", ".join(map(str, fib_sequence))[:200] + "..." if len(result_text) > 200 else result_text
            self.label_result.configure(text=f"Фиббоначи {n} чисел:")
            
        except ValueError:
            self.label_result.configure(text="Ошибка: Введите число!")

    def clear_output(self):
        """Очистка вывода"""
        self.spinbox_num.delete(0, tk.END)
        try:
            self.spinbox_num.insert(0, 10)
        except tk.TclError:
            pass
        
        self.label_result.configure(text="Результат:")

    def destroy_window(self):
        """Уничтожение окна приложения"""
        if self.root:
            self.root.quit()


def run_gui_app():
    """Запуск графического интерфейса для расчета последовательности Фиббоначи.
    
    Создаст и запустит окно с калькулятором Фиббоначи, где можно:
    - Указать количество чисел последовательности
    - Рассчитать выбранный диапазон
    - Очистить результаты
    
    Args:
        None
        
    Returns:
        int: Код выхода из приложения (0 = успешно)
    """
    app = FibonacciGUI()
    app.pack_widgets()
    return 0

if __name__ == "__main__":
    exit_code = run_gui_app()
    