'''Фиббоначи калькулятор с графическим интерфейсом на tkinter'''

import tkinter as tk
from tkinter import ttk, scrolledtextbox


class FibonacciGUI:
    """Фиббоначи калькулятор с графическим интерфейсом"""

    def __init__(self):
        self.root = None
        self.labels = {}
        self.textboxes = {}
        self.button_calc = None
        self.button_clear = None
        self.spinbox_num = None
        self.last_sequence = []

    def create_window(self):
        """Создает главное окно приложения"""
        self.root = tk.Tk()
        self.root.title("Калькулятор Фибоначчи")
        self.root.geometry("500x400")
        self.root.resizable(True, True)

    def create_labels(self):
        """Создает метки в интерфейсе"""
        # Метка для количества чисел
        label_count = tk.Label(
            self.root, text="Количество чисел:", font=("Arial", 12), pady=5
        )
        self.labels['count_label'] = label_count

        # Метка для вывода результатов
        label_result = tk.Label(
            self.root, text="Результат:", font=("Arial", 12), pady=5
        )
        self.labels['result_label'] = label_result

    def create_textboxes(self):
        """Создает текстовые поля для вывода"""
        # Текстовое поле для последовательности Фибоначчи
        frame_result = tk.Frame(self.root)
        frame_result.pack(fill=tk.X, padx=5, pady=5)

        self.textboxes['sequence'] = scrolledtext.ScrolledText(
            frame_result, width=60, height=10, font=("Courier", 10)
        )
        self.textboxes['sequence'].pack(fill=tk.BOTH, expand=True)

    def create_button_calc(self):
        """Создает кнопку для запуска расчета последовательности Фибоначчи
        
        Метод создает кнопку в интерфейсе, при нажатии на которую 
        выполняется вычисление ряда чисел Фибоначчи согласно указанному
        количеству элементов.
        
        Returns:
            tk.Button: Созданная кнопка
        """
        # Создаем контейнер для кнопок внизу окна
        button_frame = tk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=5, pady=10)

        # Создаем кнопку расчета
        self.button_calc = tk.Button(
            button_frame,
            text="Расчет последовательности",
            font=("Arial", 12),
            command=self._calculate_fibonacci,
            bg="#4CAF50",  # Зеленый цвет при нажатии
            fg="white"
        )

        # Добавляем кнопку в контейнер
        self.button_calc.pack(side=tk.LEFT, padx=5)

        # Создаем кнопку очистки
        clear_button = tk.Button(
            button_frame,
            text="Очистить",
            font=("Arial", 12),
            command=self._clear_results,
            bg="#f44336"
        )
        clear_button.pack(side=tk.LEFT, padx=5)

        return self.button_calc

    def create_button_clear(self):
        """Создает кнопку очистки результатов (опционально)"""
        pass

    def create_spinbox_num(self):
        """Создает спинбокс для ввода количества чисел"""
        # Рамка с полем для ввода
        input_frame = tk.Frame(self.root)
        input_frame.pack(fill=tk.X, padx=5, pady=5)

        # Текстовое поле
        num_field = ttk.Entry(
            input_frame, width=10, font=("Arial", 12), justify='center'
        )
        num_field.insert(0, "20")
        num_field.pack(side=tk.LEFT, padx=5)

        # Метод установки количества
        def set_count(val):
            self.last_count = val

        trace = tk.IntVar()
        num_spinbox = ttk.Spinbox(
            input_frame, from_=1, to=1000, width=6, font=("Arial", 11),
            textvariable=trace, command=set_count
        )
        self.spinbox_num = num_spinbox
        num_spinbox.pack(side=tk.LEFT, padx=5)

        # Метка количества с спинбоксом
        tk.Label(input_frame, text="чисел:", font=("Arial", 12)).pack(
            side=tk.LEFT, padx=5
        )

    def _calculate_fibonacci(self):
        """Вычисляет последовательность чисел Фибоначчи"""
        if self.spinbox_num is None:
            return

        # Получаем количество чисел из спинбокса
        try:
            count = int(self.textboxes['sequence'].__class__.__bases__[0])
            count_value = 20
        except (ValueError, AttributeError):
            # По умолчанию 20 чисел
            count_value = self.textboxes['sequence'].get('1.0', 'END').strip()

        if self.spinbox_num is not None:
            try:
                num_entries = self.spinbox_num.get()
                count_value = int(num_entries)
            except (ValueError, AttributeError):
                pass

        # Генерируем последовательность Фибоначчи
        fib_sequence = [0]  # Первое число
        if count_value > 1:
            fib_sequence.append(1)  # Второе число
            for _ in range(count_value - 2):
                next_fib = fib_sequence[-1] + fib_sequence[-2]
                fib_sequence.append(next_fib)

        # Выводим результат в текстовое поле
        result_text = "\n".join(map(str, fib_sequence))
        if hasattr(self, 'textboxes') and 'sequence' in self.textboxes:
            self.textboxes['sequence'].delete('1.0', tk.END)
            self.textboxes['sequence'].insert('1.0', result_text)

    def _clear_results(self):
        """Очищает результаты расчета"""
        if hasattr(self, 'textboxes') and 'sequence' in self.textboxes:
            self.textboxes['sequence'].delete('1.0', tk.END)

    def pack_widgets(self):
        """Расставляет виджеты в окне"""
        # Расставляем все созданные виджеты
        self.create_labels()
        
        # Текстовые поля (под метками)
        label_count = self.labels.get('count_label')
        label_result = self.labels.get('result_label')
        
        if label_count and label_result:
            frame_nums = tk.Frame(self.root)
            frame_nums.pack(fill=tk.X, padx=5, pady=5)
            
            spinbox_frame = tk.Frame(frame_nums)
            spinbox_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            if self.spinbox_num:
                self.spinbox_num.pack(side=tk.LEFT, padx=5)
                
            # Текстовое поле результатов (внизу под меткой результата)
            self.create_textboxes()

    def destroy_window(self):
        """Разрушает окно приложения"""
        if hasattr(self, 'root'):
            self.root.destroy()


def run_gui_app():
    """Запускает GUI приложение для расчета последовательности Фибоначчи"""
    app = FibonacciGUI()
    
    # Создаем окно
    app.create_window()
    
    # Создаем виджеты окна
    app.create_labels()
    app.create_textboxes()
    app.create_button_calc()
    app.create_spinbox_num()
    app.create_button_clear()
    
    # Расставляем виджеты
    app.pack_widgets()
    
    # Запускаем главный цикл
    app.root.mainloop()


# Точка входа при запуске скрипта как standalone-программы
if __name__ == "__main__":
    run_gui_app()
