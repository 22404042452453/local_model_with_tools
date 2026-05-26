'''Module for input validation and error handling utilities related to Fibonacci number generation.'''


class ValidationError(Exception):
    '''Exception raised when input validation fails.'''

    def __init__(self, message):
        """Initialize a ValidationError with an error message.
        
        Args:
            message: The error message describing the validation failure.
                    May contain format placeholders {0} for use with str.format().
        """
        self._message = message
    
    @property
    def message(self):
        """Get the error message associated with this exception."""
        return self._message


def is_valid_integer(value):
    '''Determine if a value is a valid positive integer.
    
    Args:
        value: The value to check, which may be an int or string representation.
    
    Returns:
        bool: True if the value represents a positive integer (>= 1), False otherwise.
    '''
    try:
        int_value = int(value)
        return int_value > 0
    except (ValueError, TypeError):
        return False


def validate_positive_n(n):
    '''Validate that n is a positive integer suitable for Fibonacci calculation.
    
    Args:
        n: The value to validate as a positive index/position in Fibonacci sequence.
    
    Returns:
        tuple: (is_valid, error_message) where is_valid is True if valid, 
               and error_message describes the validation failure if invalid.
    
    Raises:
        TypeError: If n cannot be converted to an integer.
        ValidationError: If n is not positive.
    '''
    try:
        n_int = int(n)
    except (ValueError, TypeError) as e:
        raise TypeError(f"Invalid input type for Fibonacci index: must be convertible to integer") from e
    
    if n_int <= 0:
        raise ValidationError("Fibonacci index must be a positive integer greater than 0")
    
    return True, None


def validate_range(value, min_value, max_value):
    '''Validate that a value is within the specified range.
    
    Args:
        value: The value to check.
        min_value: The inclusive minimum bound of the valid range.
        max_value: The inclusive maximum bound of the valid range.
    
    Returns:
        bool: True if value is within [min_value, max_value].
    
    Raises:
        ValidationError: If value is outside the specified range.
    
    Examples:
        >>> validate_range(5, 1, 10)
        True
        >>> validate_range(-1, 1, 10)
        ValidationError(Invalid range error occurred.)
    '''
    if not (min_value <= value <= max_value):
        raise ValidationError(f"Value {value} is outside the valid range [{min_value}, {max_value}]")
    
    return True


def validate_string_match(pattern, value, message_template='Input does not match required pattern'):
    '''Validate that a string matches the specified pattern.
    
    Args:
        pattern: The regex pattern to match against.
        value: The string value to validate.
        message_template: Template for error message with {0} placeholder for actual input.
    
    Returns:
        bool: True if the value matches the pattern.
    
    Raises:
        ValidationError: If the value doesn't match the pattern.
    '''
    import re
    
    try:
        compiled_pattern = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}") from e
    
    if not compiled_pattern.match(str(value)):
        error_msg = message_template.format(value)
        raise ValidationError(error_msg)
    
    return True


def get_default_max_iterations():
    '''Get default maximum number of iterations allowed for Fibonacci calculation.
    
    Returns:
        int: The default maximum number of Fibonacci iterations (number of terms).
            This limits computation to reasonable values preventing infinite loops.
    
    Notes:
        For typical educational/interactive use, 100-500 iterations is appropriate.
        Beyond ~93 terms results in extremely large numbers that may cause performance issues.
    '''
    return 400


class FibonacciValidator:
    '''Class for validating inputs to Fibonacci calculation functions.
    
    Provides reusable validation logic with configurable limits.
    Configurable maximum iterations allow adapting the validator for different use cases.
    '''

    def __init__(self, max_iterations=None):
        """Initialize the FibonacciValidator with optional custom iteration limit.
        
        Args:
            max_iterations: Optional maximum number of iterations to allow.
                           If None, defaults will be used from settings/constants.
        
        Raises:
            ValueError: If max_iterations is negative or zero.
        '''
        if max_iterations is None:
            self._max_iterations = get_default_max_iterations()
        else:
            self._max_iterations = max_iterations
            if not isinstance(max_iterations, int) or max_iterations <= 0:
                raise ValueError("max_iterations must be a positive integer")
    
    @property
    def max_iterations(self):
        """Get the maximum number of iterations allowed.
        
        Returns:
            int: The configured or default maximum iterations for Fibonacci calculations.
        '''return self._max_iterations
