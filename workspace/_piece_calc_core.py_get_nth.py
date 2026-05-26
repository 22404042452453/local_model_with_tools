def get_nth(self, n: int) -> int:
    '''Get the nth Fibonacci number (1-indexed).
    
    Args:
        n (int): Position in the sequence. Must be >= 0.
                 F(0) = 0, F(1) = 1
    
    Returns:
        int: The nth Fibonacci number.
    
    Raises:
        ValueError: If n is negative.
    '''
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return 0
    if n == 1:
        return 1
    
    prev_prev, prev = 0, 1
    for _ in range(2, n + 1):
        current = prev + prev_prev
        prev_prev = prev
        prev = current
    
    return prev
