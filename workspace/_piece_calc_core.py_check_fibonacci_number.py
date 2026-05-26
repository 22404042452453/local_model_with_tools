def check_fibonacci_number(n: int) -> bool:
    """Check if a given number exists in the Fibonacci sequence.
    
    Args:
        n (int): Number to check. Must be >= 0.
        
    Returns:
        bool: True if 'n' is a Fibonacci number, False otherwise.
    """
    # Handle edge cases
    if n < 0:
        return False
    
    # 0 and 1 are the first two Fibonacci numbers (F(0) and F(1))
    if n == 0 or n == 1:
        return True
    
    # Use the mathematical property: n is a Fibonacci number iff
    # either (5*n^2 + 4) or (5*n^2 - 4) is a perfect square
    def is_perfect_square(x: int) -> bool:
        """Check if x is a perfect square."""
        if x < 0:
            return False
        sqrt_x = int(x**0.5)
        return sqrt_x * sqrt_x == x
    
    test1 = 5 * n * n + 4
    test2 = 5 * n * n - 4
    
    return is_perfect_square(test1) or is_perfect_square(test2)
