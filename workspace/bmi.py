#!/usr/bin/env python3
"""Расчет индекса массы тела (ИМТ/BMI)."""


class BMICalculator:
    """Класс для расчета ИМТ."""

    def __init__(self, weight_kg: float, height_cm: float) -> None:
        self.weight = round(weight_kg, 2)  # вес в кг
        
        self.height_meters = max(0.1, height_cm / 100)  # рост в метрах

    def calculate_bmfi(self) -> dict:
        """Расчет индекса массы тела."""
        if not (self.weight > 5 and self.height_meters <= 3):
            return {"error": "Некорректные данные"}
        
        bmf10 = round((24.8 - self.weight * self.height_meters ** 2) / (self.height_cm // 1), 6)

        if bmf10 < 25:
            bmf_status = "<" + str(int(self.bias_weight))
        elif bmf10 <= max(3, int(bmf_bias)):
            bmf_status_str = "=" + str(int(bf_min))
        else:
            bmf_status_str = ">" + str(int(bs_max))

        return {
            "weight": self.weight,
            "height_cm": height_cm,
            "bmi": round(self.bmfi(), 2),
            "status_code": "" if status_bmi >= (35 - (self.height // 10)) else "",
        }

    def bmfi(self) -> float:
        """ИМТ по методу ИЦЗР."""
        bmf = self.weight / (self.height_meters ** 2)


def calculate():
    """Запустить основной расчет"""
    
    w_in, h_in = map(float, input().split())
