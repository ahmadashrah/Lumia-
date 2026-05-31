from ._runner import run as _run


def run(payload: dict) -> dict:
    return _run("content", payload, max_tokens=2000)
