from ._runner import run as _run


def run(payload: dict) -> dict:
    return _run("competitive", payload, max_tokens=2500)
