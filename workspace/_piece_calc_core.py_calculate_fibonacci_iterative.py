def calculate_fibonacci_iterative(n: int) -> int:
    """Calculate nth Fibonacci number using iterative approach.
    
    Args:
        n (int): Position in the sequence. Must be >= 0.
        
    Returns:
        int: The nth Fibonacci number.
    
    Raises:
        ValueError: If n is negative.
    
    Examples:
        >>> calculate_fibonacci_iterative(0)
        0
        >>> calculate_fibonacci_iterative(1)
        1
        >>> calculate_fibonacci_iterative(2)
        1
        >>> calculate_fibonacci_iterative(10)
        55
    
    Notes:
        The Fibonacci sequence starts with F(0)=0, F(1)=1, and each subsequent
        number is the sum of the two preceding numbers.
    """
    if n < 0:
        raise ValueError(f"n must be a non-negative integer, got {n}")
    
    if n == 0:
        return 0
    
    if n == 1:
        return 1
    
    # Iterative calculation for n >= 2
    prev, curr = 0, 1
    for _ in range(2, n + 1):
        prev, curr = curr, prev + curr
    
    return curr
