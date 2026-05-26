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
