class APIError(Exception):
 def __init__(self,status_code,code,message,details=None):super().__init__(message);self.status_code=status_code;self.code=code;self.message=message;self.details=details or {}
