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