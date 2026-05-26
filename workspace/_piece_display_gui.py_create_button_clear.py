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
