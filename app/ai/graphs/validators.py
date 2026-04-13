from app.core.errors import ApiError


def validate_run_result(result: dict) -> dict:
    if "summary" not in result:
        raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
    result.setdefault("score", None)
    result.setdefault("build", [])
    result.setdefault("runes", None)
    result.setdefault("explanations", [])
    result.setdefault("alternatives", [])
    return result
