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