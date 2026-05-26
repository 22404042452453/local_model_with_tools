"""
core calculation functions (generate sequence, get nth Fibonacci)
"""


from typing import List, Optional


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


def calculate_fibonacci_matrix(n: int) -> int:
    """Calculate nth Fibonacci number using matrix exponentiation.
    
    Args:
        n (int): Position in the sequence. Must be >= 0.
        
    Returns:
        int: The nth Fibonacci number.
        
    Notes:
        Uses matrix exponentiation for O(log n) time complexity.
        F(0) = 0, F(1) = 1, F(2) = 1, F(3) = 2, ...
        
        The transformation matrix M = [[1, 1], [1, 0]] raised to power n
        gives: M^n * [F(1), F(0)]^T = [F(n+1), F(n)]^T
    """
    # Base case for n=0 and n=1
    if n == 0:
        return 0
    if n == 1 or n == 2:
        return 1
    
    # Matrix exponentiation to compute M^n where M = [[1, 1], [1, 0]]
    a, b = multiply_matrix([[1, 1], [1, 0]], n)
    
    # F(n) is found in position [1][0] of M^(n-1) applied to initial vector
    # For M^n applied to [1, 0]^T, we get [F(n+1), F(n)]^T
    return b


def multiply_matrix(matrix: List[List[int]], exponent: int) -> List[List[int]]:
    """
    Raises a 2x2 matrix to the power of exponent using binary exponentiation.
    
    Args:
        matrix (List[List[int]]): A 2x2 matrix [[a, b], [c, d]]
        exponent (int): Positive integer exponent
    
    Returns:
        List[List[int]]: The matrix raised to the given power.
    """
    # Identity matrix for 2x2 matrices
    identity = [[1, 0], [0, 1]]
    
    result = identity[:]
    base = [row[:] for row in matrix]
    
    while exponent > 0:
        if exponent % 2 == 1:
            result = matrix_multiply(result, base)
        base = matrix_multiply(base, base)
        exponent //= 2
    
    return result


def matrix_multiply(A: List[List[int]], B: List[List[int]]) -> List[List[int]]:
    """
    Multiplies two 2x2 matrices.
    
    Args:
        A (List[List[int]]): First 2x2 matrix
        B (List[List[int]]): Second 2x2 matrix
    
    Returns:
        List[List[int]]: The product A * B
    """
    c00 = A[0][0] * B[0][0] + A[0][1] * B[1][0]
    c01 = A[0][0] * B[0][1] + A[0][1] * B[1][1]
    c10 = A[1][0] * B[0][0] + A[1][1] * B[1][0]
    c11 = A[1][0] * B[0][1] + A[1][1] * B[1][1]
    
    return [[c00, c01], [c10, c11]]


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


'''Module for calculating Fibonacci sequence numbers.
This module provides functionality to:
- Generate the complete Fibonacci sequence (up to N terms)
- Get the nth Fibonacci number efficiently
- Support various calculation methods
'''

from typing import List, Optional


class FibonacciCalculator:
    '''Class providing various methods for Fibonacci number calculations.'''
    
    def __init__(self):
        '''Initialize the Fibonacci calculator.
        
        Args:
            None
        '''
        pass


'''Module for calculating Fibonacci sequence numbers.
This module provides functionality to:
- Generate the complete Fibonacci sequence (up to N terms)
- Get the nth Fibonacci number efficiently
- Support various calculation methods
'''

from typing import List, Optional


class FibonacciCalculator:
    '''Class providing various methods for Fibonacci number calculations.'''
    
    def __init__(self):
        '''Initialize the Fibonacci calculator.
        
        Args:
            None
        '''
        pass
    
    def generate_sequence(self, n: int) -> List[int]:
        '''Generate a sequence of the first n Fibonacci numbers.
        
        Args:
            n (int): Number of Fibonacci terms to generate. Must be >= 0.
        
        Returns:
            List[int]: List containing the first n Fibonacci numbers.
            Returns empty list if n <= 0.
        
        Raises:
            ValueError: If n is negative.
        '''
        if n < 0:
            raise ValueError(f"n must be a non-negative integer, got {n}")
        
        if n == 0:
            return []
        
        # Initialize the first two Fibonacci numbers
        sequence = [0]
        if n >= 1:
            sequence.append(1)
        
        # Generate remaining Fibonacci numbers up to n terms
        for i in range(2, n):
            next_fib = sequence[i - 1] + sequence[i - 2]
            sequence.append(next_fib)
        
        return sequence


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


def validate_input(self, n: int) -> bool:
    """Validate that n is a suitable Fib index.
    
    Args:
        n (int): Value to check.
    
    Returns:
        bool: True if valid, False otherwise.
    """
    return n >= 0
