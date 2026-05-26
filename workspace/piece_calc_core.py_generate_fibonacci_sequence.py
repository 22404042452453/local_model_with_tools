def generate_fibonacci_sequence(n: int) -> list[int]:
    """Generate the first n Fibonacci numbers using iterative approach.

    Args:
        n (int): Number of terms to generate.

    Returns:
        List[int]: The Fibonacci sequence up to n terms.
        Returns empty list for n <= 0.
    """
    if n <= 0:
        return []
    
    if n == 1:
        return [0]
    
    # Start with the first two Fibonacci numbers
    fib = [0, 1]
    
    # Generate remaining numbers iteratively
    for _ in range(2, n):
        fib.append(fib[-1] + fib[-2])
    
    return fib
