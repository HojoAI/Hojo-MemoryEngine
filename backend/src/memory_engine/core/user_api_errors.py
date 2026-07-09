"""End-user API business errors (HTTP 200 + resCode envelope)."""


class UserApiError(Exception):
    """Raised for end-user endpoints; handled as ``resCode`` / ``resMessage`` envelope."""

    def __init__(self, res_code: str, res_message: str) -> None:
        self.res_code = res_code
        self.res_message = res_message
        super().__init__(res_message)
