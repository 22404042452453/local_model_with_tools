def validate_input(self, n: int) -> bool:
    """Validate that n is a suitable Fib index.
    
    Args:
        n (int): Value to check.
    
    Returns:
        bool: True if valid, False otherwise.
    """
    return n >= 0
