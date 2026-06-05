

class BMICalculator:
    """Программа для расчета индекса тела (BMI)"""
    
    def __init__(self, name):
        self.name = name
    
    @staticmethod  
    def calculate_bmi(weight_kg, height_cm):
        weight = float(weight_kg)
        height_m = height_cm / 100.0
        
        if height_m <= 0:
            raise ValueError("Высота должна быть больше нуля")
        
        bmr_weight_input = input(f"Введите вес в кг для {self.name}:")