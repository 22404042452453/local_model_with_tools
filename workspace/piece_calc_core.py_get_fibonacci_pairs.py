def get_fibonacci_pairs(n: int) -> List[tuple]:
    """Get n pairs of consecutive Fibonacci numbers.
    
    Args:
        n (int): Number of pairs to generate.
        
    Returns:
        List[tuple]: List of (F(i), F(i+1)) tuples.
        
    Examples:
        >>> get_fibonacci_pairs(5)
        [(0, 1), (1, 1), (1, 2), (2, 3), (3, 5)]
    """
    if n <= 0:
        return []
    
    pairs = []
    a, b = 0, 1
    
    for _ in range(n):
        pairs.append((a, b))
        a, b = b, a + b
    
    return pairs
