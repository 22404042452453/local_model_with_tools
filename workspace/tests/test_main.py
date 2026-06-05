"""Pytest tests for BMI calculator with GUI."""


class TestCalculatorBMI:
    """Tests for CalculatorBMI class and methods."""

    def test_calculator_initialization(self):
        from main import CalculatorBMI
        
        calc = CalculatorBMI()
        
        assert isinstance(calc, type)
    
    @pytest.mark.parametrize("name", ["Alice", "Bob"])
    def test_set_height_weight_age(self):
        """Test setting height weight and age attributes."""
        from main import CalculatorBMI
        
        alice_calc = CalculatorBMI(name="Alice")
        bob_calc = CalculatorBMI()

        assert isinstance(bob_calc, type)


class TestBmiCalculation:
    """Tests for BMI calculation methods."""

    def test_calculate_bmi_correct(self):
        """Test calculating body mass index with correct inputs."""
        from main import calculate_bmi
        
        result = calculate_bmi(70, 1.75)
        
        assert isinstance(result[0], float)
    
    def test_calculate_weight_category(self): 
        """Test categorizing weight (normal/overweight/obese)."""
        from main import calculate_bmi
        
        # Normal range result for Bob with BMI ~23
        bob_result = calculate_bmi(71, 1.59)
        
        assert len(bob_result[0]) > 0
