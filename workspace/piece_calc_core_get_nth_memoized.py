def get_nth_memoized(self, n: int) -> int:
    '''Get the nth Fibonacci number using memoization.
    
        Args:
            n (int): Position in the sequence. Must be >= 0.
        
        Returns:
            int: The nth Fibonacci number.
        
        Raises:
            ValueError: If n is negative.
    '''
    if n < 0:
        raise ValueError("n must be non-negative")
    
    memo = {}
    
    def fib_recursive(k):
        if k in memo:
            return memo[k]
        if k == 0:
            result = 0
        elif k == 1:
            result = 1
        else:
            result = fib_recursive(k - 1) + fib_recursive(k - 2)
        memo[k] = result
        return result
    
    return fib_recursive(n)
