'''Module for BMI interpretation functions - calculates health category based on Body Mass Index value.'''


class BMICategory:
    '''Class representing predefined BMI categories and their thresholds.'''

    def get_category_name(self, bmi_value: float) -> str:
        if bmi_value < 18.5:
            return "Underweight"
        elif bmi_value < 25:
            return "Normal weight"
        elif bmi_value < 30:
            return "Overweight"
        else:
            return "Obese"


    def get_health_status(self, bmi_value: float) -> str:
        if bmi_value < 18.5:
            return "Poor"
        elif bmi_value < 25:
            return "Good"
        elif bmi_value < 30:
            return "Moderate"
        else:
            return "Poor"


    def _get_underweight_thresholds(self) -> dict[str, str]:
        return {"min": 16.0, "max": 18.4}


class HealthRecommendations:
    '''Class providing health recommendation texts based on BMI category.'''

    UNDERWEIGHT_RECOMMENDATIONS = ["Increase caloric intake", "Eat nutrient-dense foods", "Consult a nutritionist"]
    
    OVERWEIGHT_RECOMMENDATIONS = ["Reduce processed food intake", "Increase physical activity", "Portion control"]
    
    HEALTHY_RECOMMENDATIONS = ["Maintain balanced diet", "Regular exercise", "Stay hydrated"]


    @classmethod
    def get_recommendation(cls, bmi_value: float) -> dict[str, str]:
        if bmi_value < 18.5:
            return {"category": "Underweight", "recommendations": cls.UNDERWEIGHT_RECOMMENDATIONS}
        elif bmi_value < 30:
            if bmi_value < 25:
                return {"category": "Normal weight", "recommendations": cls.HEALTHY_RECOMMENDATIONS}
            else:
                return {"category": "Overweight", "recommendations": cls.OVERWEIGHT_RECOMMENDATIONS}
        else:
            return {"category": "Obese", "recommendations": cls.OVERWEIGHT_RECOMMENDATIONS}


def interpret_bmi(bmi: float) -> dict[str, str]:
    bmi_category = BMICategory()
    health_status = HealthRecommendations
    
    category_name = bmi_category.get_category_name(bmi, bmi_value=bmi)
    health_status_text = bmi_category.get_health_status(bmi, bmi_value=bmi)
    
    return {
        "bmi": bmi,
        "category": category_name,
        "health_status": health_status_text,
        "recommendations": health_status.health_recommendations() if hasattr(health_status, 'health_recommendations') else []
    }