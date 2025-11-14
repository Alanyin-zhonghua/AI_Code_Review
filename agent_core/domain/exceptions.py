class BusinessError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400, **extra):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra
        super().__init__(message)


class NetworkError(BusinessError):
    pass


class ApiError(BusinessError):
    pass


class RateLimitError(BusinessError):
    pass


class ValidationError(BusinessError):
    pass