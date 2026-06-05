# Implementation Plan: GUI Calculator for Body Mass Index (BMI)

## Task

Программа с графическим интерфейсом на Python для расчёта индекса массы тела (ИМТ) с отображением результатов, интерпретацией и возможностями ввода антропометрических данных.

## Technology Stack

- **Python 3.11+** (stdlib only)
- **tkinter** - встроенный GUI фреймворк для создания оконного интерфейса
- **math** - извлечение квадратных корней для расчёта ИМТ
- **json** - сохранение результатов в формат JSON при необходимости

Выбранный стек использует только стандартные библиотеки Python (не требует установки дополнительных пакетов).

## Files

```
bmi_app/                    # Корневая директория проекта
├── main.py                 # Главный файл приложения + точка входа
├── bmi.py                  # Математическая логика расчёта IMT
├── interpreter.py          # Функции интерпретации результатов
└── style.py                # Стилизация и константы приложения
```

## File Details

### main.py
- `class BMIApp`: основной класс GUI приложения
  - `__init__(self)`: инициализация Tkinter окна
  - `create_widgets(self)`: создание всех виджетов интерфейса
  - `calculate_bmi(self)`: метод расчёта ИМТ по нажатию кнопки
  - `show_result(self, bmi)`: отрисовка результата в окне
  - `interpret(self, bmi)`: вызов интерпретации значения
  - `save_to_json(self)`: сохранение данных
- `def main()`: точка входа в приложение, создание экземпляра BMIApp

### bmi.py
- `class BMICalculator`: класс для расчёта ИМТ
  - `__init__(self, weight_kg: float, height_cm: float)`: инициализация вес и рост
  - `calculate(self) -> float`: вычисление ИМТ по формуле m/h²
  - `get_result_str(self) -> str`: форматирование результата для вывода

### interpreter.py
- `def interpret_bmi(bmi: float) -> dict`: интерпретация значения ИМТ
  - Возвращает словарь с ключами: {'category': str, 'status': str, 'health_recommendations': list}
- `BMICATEGORIES = dict`: константа со шкалой ВОЗ (underweight, normal weight, overweight, obesity grade I/II/III)

### style.py
- `FONT_FAMILY: str = "Arial"` - семейство шрифтов
- `PRIMARY_COLOR: Tuple[float, float, float]` - основная цветовая схема
- `BACKGROUND_COLOR` - цвет фона формы результатов
- `BUTTON_STYLE: tuple` - настройки стилей кнопок (paddings, colors)

## Implementation Order

1. **main.py** — создать каркас GUI приложения с окном Tkinter и базовыми виджетами (labels, entry, buttons)
2. **bmi.py** — реализовать формулу ИМТ и класс для расчёта (m/h² в кг/см² × 10000)
3. **interpreter.py** — создать словарь категорий согласно рекомендациям ВОЗ
4. **style.py** — определить цветовую схему и константы интерфейса
5. **main.py** — интегрировать все модули, добавить обработку событий кнопок
6. **Тестирование**: unit-тесты для расчётов, тест GUI через unittest

## Testing

### Что тестировать:
1. Формула ИМТ: проверять корректность вычислений (например, вес=70кг, рост=175см → ИМТ≈22.49)
2. Интерпретация значений: тесты на граничные значения (18.5, 25, 30 кг/м²)
3. GUI виджеты проверять визуально при запуске main.py

### Как тестировать:
```python
# test_bmi_app.py (разделено в отдельный файл)
import unittest
from bmi import BMICalculator

class TestBMICalculator(unittest.TestCase):
    def setUp(self):
        self.calculator = BMICalculator(weight_kg=70.0, height_cm=175.0)
    
    def test_standard_bmi(self):
        expected = 22.496...  # round(70/(1.75**2), 2)
        actual = self.calculator.calculate()
        self.assertAlmostEqual(actual, expected, delta=0.01)

    def test_underweight_result(self):
        calc = BMICalculator(weight_kg=48, height_cm=160)
        result = calc.calculate()
        self.assertLess(result, 18.5)
```

Запуск тестов командой: `python -m unittest test_bmi_app.py`
