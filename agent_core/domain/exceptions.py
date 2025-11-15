"""统一业务异常模型。

所有跨模块抛出的业务级错误都应该继承自 BusinessError，
便于在 API 层或 UI 层做统一捕获与用户提示。
"""


class BusinessError(Exception):
    """业务异常基类。

    Attributes:
        code: 机器可读错误码（如 "STORE_READ_ERROR"）。
        message: 用户可读错误信息。
        http_status: 映射到 HTTP 时可用的状态码，默认 400。
        extra: 其他补充字段（例如 trace_id、provider 等）。
    """

    def __init__(self, code: str, message: str, http_status: int = 400, **extra):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra
        super().__init__(message)


class NetworkError(BusinessError):
    """网络层错误，例如连接失败、超时等。"""


class ApiError(BusinessError):
    """第三方 API 返回非 2xx/429 错误时抛出。"""


class RateLimitError(BusinessError):
    """Provider 限流错误，由上层负责重试/退避策略。"""


class ValidationError(BusinessError):
    """参数或配置校验失败。"""
