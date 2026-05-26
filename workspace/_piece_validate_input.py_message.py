class ValidationError(Exception):
    '''Exception raised when input validation fails.'''

    def __init__(self, message):
        '''Initialize ValidationError with an error message.
        
        Args:
            message: A human-readable error message describing the validation failure.
        '''
        # Normalize message to string (allow subclasses to customize behavior)
        self._message = message
    
    @property
    def message(self):
        '''Get the formatted error message string.
        
        Returns:
            The error message string that describes what validation failed.
        '''
        return self._message if isinstance(self._message, str) else str(self._message)
