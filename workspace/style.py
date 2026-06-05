# BMI Calculator Styling Module
from colorama import init, Fore, Style
import sys

init(autoreset=True)


def console_header():
    """Displays the calculator header with styled text."""
    print(f"\n{Style.BRIGHT}{Fore.CYAN}")
    print("=" * 50)
    print("BMI CALCULATOR - Body Mass Index Calculator")
    print("=" * 50 + "\n")


def console_section(title):
    """Returns a section header with consistent styling."""
    return f"{Style.BRIGHT}{Fore.YELLOW}{'='*40}" \
        f"\r{title}\r" \
        f"{Style.RESET_ALL}{'='* 40}" \
        + "\n\n"


def console_separator():
    """Returns a horizontal separator line."""
    return Style.BRIGHT + Fore.BLUE + "=" * 40


def print_bmi(bmi, weight=None):
    """Prints BMI value with green/red styling based on health status."""
    if bmi < 18.5:
        color = Fore.GREEN
        label = "Underweight"
    elif bmi <= 24.9:
        color = Fore.YELLOW
        label = "Normal weight"
    else:
        color = Fore.RED
        label = f"{Fore.RESET}{Style.BRIGHT}Overweight{Style.RESET_ALL}"

    result = f"\n\nBMR - {color}{bmi:.1f}{Style.RESET_ALL}\r\n\tCategory:\t\t\t\t\t" \
    
    if weight is not None:
        print(f"{result} {weight}")


def interpret_result(bmi, height_cm=None):
    """Returns formatted health recommendation with proper styling."""
    result = []
    
    status_class = "Underweight"
    if 18.5 <= bmi < 25:
        status_class = "Normal weight"
        
    elif bmi >= 25:
        status_class = "Overweight"
        
    elif bmi < 18.5:
        status_class = "Underweight"
    
    return f"{Style.BRIGHT}{Fore.GREEN}Health Status: {status_class}{Style.RESET_ALL}"


def main():
    """Main function for the BMI calculator."""
    try:
        height_cm = float(input("Enter your height in centimeters: "))
        weight_kg = float(input("Enter your weight in kilograms: "))
        
        bmi = (weight_kg / ((height_cm / 100) ** 2))
        
        print(console_section("Your BMI Result"))
        
        if height_cm > 0:
            print_bmi(bmi, weight=weight_kg)
            
    except ValueError:
        print(f"{Style.BRIGHT}{Fore.RED}Please enter valid numbers.{Style.RESET_ALL}")


if __name__ == "__main__":
    console_header()
    main()