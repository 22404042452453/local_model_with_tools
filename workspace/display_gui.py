"""
optional tkinter-based visual output
"""


import tkinter as tk
from tkinter import ttk, scrolledtextbox


def calculate_fibonacci_recursive(n: int) -> int:
    """Calculate nth Fibonacci number using naive recursive approach.
    
    Args:
        n (int): Position in the sequence. Must be >= 0.
        
    Returns:
        int: The nth Fibonacci number.
        
    Raises:
        ValueError: If n is negative.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    
    # Base cases
    if n == 0:
        return 0
    elif n == 1:
        return 1
    
    # Recursive case for n >= 2
    return calculate_fibonacci_recursive(n - 1) + calculate_fibonacci_recursive(n - 2)


def calculate_fibonacci_iterative(n: int) -> int:
    """Calculate nth Fibonacci number using iterative approach.
    
    Args:
        n (int): Position in the sequence. Must be >= 0.
        
    Returns:
        int: The nth Fibonacci number.
    
    Raises:
        ValueError: If n is negative.
    
    Examples:
        >>> calculate_fibonacci_iterative(0)
        0
        >>> calculate_fibonacci_iterative(1)
        1
        >>> calculate_fibonacci_iterative(2)
        1
        >>> calculate_fibonacci_iterative(10)
        55
    
    Notes:
        The Fibonacci sequence starts with F(0)=0, F(1)=1, and each subsequent
        number is the sum of the two preceding numbers.
    """
    if n < 0:
        raise ValueError(f"n must be a non-negative integer, got {n}")
    
    if n == 0:
        return 0
    
    if n == 1:
        return 1
    
    # Iterative calculation for n >= 2
    prev, curr = 0, 1
    for _ in range(2, n + 1):
        prev, curr = curr, prev + curr
    
    return curr


def calculate_fibonacci_matrix(n: int) -> int:
    """Calculate nth Fibonacci number using matrix exponentiation.
    
    Args:
        n (int): Position in the sequence. Must be >= 0.
        
    Returns:
        int: The nth Fibonacci number.
        
    Notes:
        Uses matrix exponentiation for O(log n) time complexity.
        F(0) = 0, F(1) = 1, F(2) = 1, F(3) = 2, ...
        
        The transformation matrix M = [[1, 1], [1, 0]] raised to power n
        gives: M^n * [F(1), F(0)]^T = [F(n+1), F(n)]^T
    """
    # Base case for n=0 and n=1
    if n == 0:
        return 0
    if n == 1 or n == 2:
        return 1
    
    # Matrix exponentiation to compute M^n where M = [[1, 1], [1, 0]]
    a, b = multiply_matrix([[1, 1], [1, 0]], n)
    
    # F(n) is found in position [1][0] of M^(n-1) applied to initial vector
    # For M^n applied to [1, 0]^T, we get [F(n+1), F(n)]^T
    return b


def multiply_matrix(matrix: List[List[int]], exponent: int) -> List[List[int]]:
    """
    Raises a 2x2 matrix to the power of exponent using binary exponentiation.
    
    Args:
        matrix (List[List[int]]): A 2x2 matrix [[a, b], [c, d]]
        exponent (int): Positive integer exponent
    
    Returns:
        List[List[int]]: The matrix raised to the given power.
    """
    # Identity matrix for 2x2 matrices
    identity = [[1, 0], [0, 1]]
    
    result = identity[:]
    base = [row[:] for row in matrix]
    
    while exponent > 0:
        if exponent % 2 == 1:
            result = matrix_multiply(result, base)
        base = matrix_multiply(base, base)
        exponent //= 2
    
    return result


def matrix_multiply(A: List[List[int]], B: List[List[int]]) -> List[List[int]]:
    """
    Multiplies two 2x2 matrices.
    
    Args:
        A (List[List[int]]): First 2x2 matrix
        B (List[List[int]]): Second 2x2 matrix
    
    Returns:
        List[List[int]]: The product A * B
    """
    c00 = A[0][0] * B[0][0] + A[0][1] * B[1][0]
    c01 = A[0][0] * B[0][1] + A[0][1] * B[1][1]
    c10 = A[1][0] * B[0][0] + A[1][1] * B[1][0]
    c11 = A[1][0] * B[0][1] + A[1][1] * B[1][1]
    
    return [[c00, c01], [c10, c11]]


def check_fibonacci_number(n: int) -> bool:
    """Check if a given number exists in the Fibonacci sequence.
    
    Args:
        n (int): Number to check. Must be >= 0.
        
    Returns:
        bool: True if 'n' is a Fibonacci number, False otherwise.
    """
    # Handle edge cases
    if n < 0:
        return False
    
    # 0 and 1 are the first two Fibonacci numbers (F(0) and F(1))
    if n == 0 or n == 1:
        return True
    
    # Use the mathematical property: n is a Fibonacci number iff
    # either (5*n^2 + 4) or (5*n^2 - 4) is a perfect square
    def is_perfect_square(x: int) -> bool:
        """Check if x is a perfect square."""
        if x < 0:
            return False
        sqrt_x = int(x**0.5)
        return sqrt_x * sqrt_x == x
    
    test1 = 5 * n * n + 4
    test2 = 5 * n * n - 4
    
    return is_perfect_square(test1) or is_perfect_square(test2)


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


'''Module for calculating Fibonacci sequence numbers.
This module provides functionality to:
- Generate the complete Fibonacci sequence (up to N terms)
- Get the nth Fibonacci number efficiently
- Support various calculation methods
'''

from typing import List, Optional


class FibonacciCalculator:
    '''Class providing various methods for Fibonacci number calculations.'''
    
    def __init__(self):
        '''Initialize the Fibonacci calculator.
        
        Args:
            None
        '''
        pass


'''Module for calculating Fibonacci sequence numbers.
This module provides functionality to:
- Generate the complete Fibonacci sequence (up to N terms)
- Get the nth Fibonacci number efficiently
- Support various calculation methods
'''

from typing import List, Optional


class FibonacciCalculator:
    '''Class providing various methods for Fibonacci number calculations.'''
    
    def __init__(self):
        '''Initialize the Fibonacci calculator.
        
        Args:
            None
        '''
        pass
    
    def generate_sequence(self, n: int) -> List[int]:
        '''Generate a sequence of the first n Fibonacci numbers.
        
        Args:
            n (int): Number of Fibonacci terms to generate. Must be >= 0.
        
        Returns:
            List[int]: List containing the first n Fibonacci numbers.
            Returns empty list if n <= 0.
        
        Raises:
            ValueError: If n is negative.
        '''
        if n < 0:
            raise ValueError(f"n must be a non-negative integer, got {n}")
        
        if n == 0:
            return []
        
        # Initialize the first two Fibonacci numbers
        sequence = [0]
        if n >= 1:
            sequence.append(1)
        
        # Generate remaining Fibonacci numbers up to n terms
        for i in range(2, n):
            next_fib = sequence[i - 1] + sequence[i - 2]
            sequence.append(next_fib)
        
        return sequence


def get_nth(self, n: int) -> int:
    '''Get the nth Fibonacci number (1-indexed).
    
    Args:
        n (int): Position in the sequence. Must be >= 0.
                 F(0) = 0, F(1) = 1
    
    Returns:
        int: The nth Fibonacci number.
    
    Raises:
        ValueError: If n is negative.
    '''
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return 0
    if n == 1:
        return 1
    
    prev_prev, prev = 0, 1
    for _ in range(2, n + 1):
        current = prev + prev_prev
        prev_prev = prev
        prev = current
    
    return prev


def create_labels(self):
    """Создает метки (labels) для отображения информации о вычислениях Фибоначчи
    
    Создаются следующие метки:
    - Label с текстом "Число Фибоначчи" — для вывода значений последовательности
    - Label с текстом "Индекс в последовательности" — для отображения номера элемента
    - Label с текстом "Количество вычисленных чисел" — счетчик рассчитанных элементов
    
    Каждая метка добавляется в self.labels словарь и позиционируется в сетке.
    """
    # Создаем первую метку: заголовок/информация о последовательности
    label_seq_info = tk.Label(
        self.window_window,
        text="Число Фибоначчи:",
        font=('Helvetica', 10),
        anchor='w'
    )
    label_seq_info.grid(row=1, column=0, sticky='e', padx=5, pady=3)
    
    # Создаем заголовок для индекса
    label_index_text = tk.Label(
        self.window_window,
        text="Индекс в последовательности:",
        font=('Helvetica', 10),
        anchor='w'
    )
    label_index_text.grid(row=2, column=0, sticky='e', padx=5, pady=3)
    
    # Создаем метку для количества вычисленных элементов
    label_count_text = tk.Label(
        self.window_window,
        text="Количество вычисленных чисел:",
        font=('Helvetica', 10),
        anchor='w'
    )
    label_count_text.grid(row=3, column=0, sticky='e', padx=5, pady=3)
    
    # Сохраняем ссылки на метки в словаре для удобного доступа
    self.labels = {
        'seq_info': label_seq_info,
        'index': label_index_text,
        'count': label_count_text
    }


'''Метод для создания текстовых полей отображения результатов в GUI калькулятора Фибоначчи.'''

class FibonacciGUI:
    """Фиббоначи калькулятор с графическим интерфейсом"""

    def __init__(self): pass

    def create_window(self): pass

    def create_labels(self): pass

    def create_textboxes(self):
        """Создание текстовых полей для отображения результатов расчета фиббоначи последовательности.
        
        Создает:
        - Поле для отображения результата вычислений (последовательность Фибоначчи)
        - Поля для вывода информации о расчете
        
        Args:
            self: экземпляр класса FibonacciGUI
            
        Returns:
            void
        """
        # Создаем текстовое поле для отображения последовательности Фибоначчи
        self.textbox_fibonacci = scrolledtextbox.ScrolledTextbox(
            self.window,
            width=50,
            height=8
        )
        
        # Настраиваем стиль и содержимое поля результата
        self.textbox_fibonacci['state'] = 'disabled'  # По умолчанию поле только для чтения
        self.textbox_fibonacci.grid(row=2, column=0, columnspan=2, padx=5, pady=10)


    def create_button_calc(self): pass

    def create_button_clear(self): pass

    def create_spinbox_num(self): pass

    def pack_widgets(self): pass

    def destroy_window(self): pass


def run_gui_app(): pass


def validate_input(self, n: int) -> bool:
    """Validate that n is a suitable Fib index.
    
    Args:
        n (int): Value to check.
    
    Returns:
        bool: True if valid, False otherwise.
    """
    return n >= 0


def create_button_clear(self):
    """Создает и настраивает кнопку очистки результатов расчета.
    
    Кнопка запускает метод clear_results() для сброса:
    - полей ввода в значения по умолчанию
    - полей вывода в пустое состояние
    - кнопок интерфейса
    
    :return: созданный ttk.Button объект
    """
    
    btn_clear = ttk.Button(
        self.window_root,
        text="Очистить",
        command=self.clear_results
    )
    
    return btn_clear


"""Implementation of pack_widgets method for FibonacciGUI class."""

def pack_widgets(self):
    """Упаковать все виджеты интерфейса в сетку.
    
    Метод организует раскладку всех созданных виджетов (метки, поля ввода, 
    кнопки) в виде сетки с помощью метода grid(). Виджеты размещаются логически:
    - верхняя строка: заголовок 'Калькулятор Фибоначчи' и кнопка вычисления
    - вторая строка: поле для вывода последовательности и кнопка очистки
    
    Args: self: ссылка на экземпляр класса FibonacciGUI
    
    Returns: None
    """
    # Первая строка: заголовок и кнопка вычисления
    self.title_label.grid(
        row=0, column=0, columnspan=2, padx=10, pady=5, sticky='ew'
    )
    
    self.calc_button.grid(
        row=0, column=0, rowspan=2, padx=5, pady=5, 
        sticky='nesw', ipadx=15, ipady=10
    )
    
    # Вторая строка: текстовое поле для вывода
    self.output_label.grid(
        row=1, column=1, padx=10, pady=5, sticky='ew'
    )
    
    self.clear_button.grid(
        row=1, column=0, rowspan=2, padx=5, pady=5, 
        sticky='nesw', ipadx=15, ipady=8
    )
    
    # Третья строка: spinbox для ввода количества чисел
    self.spinner_label.grid(
        row=2, column=0, columnspan=2, padx=10, pady=5, 
        sticky='ew'
    )
    
    self.spinbox_grid.grid(
        row=3, column=0, columnspan=2, padx=10, pady=5
    )


'''Complete implementation of destroy_window method for FibonacciGUI.'''


class FibonacciGUI:
    """Фиббоначи калькулятор с графическим интерфейсом"""

    def __init__(self): pass

    def create_window(self): pass

    def create_labels(self): pass

    def create_textboxes(self): pass

    def create_button_calc(self): pass

    def create_button_clear(self): pass

    def create_spinbox_num(self): pass

    def pack_widgets(self): pass

    def destroy_window(self):
        """Уничтожает/закрывает окно графического интерфейса.
        
        Метод закрывает созданные виджеты и окно приложения,
        очищая память от GUI компонентов. Вызывается по команде закрытия
        программы или кнопке выхода.
        
        Returns:
            None
        """
        self.root.destroy()


def run_gui_app(): pass
