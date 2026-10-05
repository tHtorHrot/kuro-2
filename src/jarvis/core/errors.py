class ApplicationError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        self.status = status
        self.code = code
        self.detail = detail
        super().__init__(code)


class UnsafeDatabaseRole(RuntimeError):
    pass
