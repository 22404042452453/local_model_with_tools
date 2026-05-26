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
