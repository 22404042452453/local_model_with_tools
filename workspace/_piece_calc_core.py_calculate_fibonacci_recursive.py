def calculate_fibonacci_recursive(n: int) -> int:
    """Calculate nth Fibonacci number using naive recursive approach.
    
    Args:
        n (int): Position in the sequence. Must be >= 0.
        
    Returns:
        int: The nth Fibonacci number.
        
    Raises:
        ValueError: If n is negative.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    
    # Base cases
    if n == 0:
        return 0
    elif n == 1:
        return 1
    
    # Recursive case for n >= 2
    return calculate_fibonacci_recursive(n - 1) + calculate_fibonacci_recursive(n - 2)
