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
