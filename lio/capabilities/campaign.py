from ._runner import run as _run


def run(payload: dict) -> dict:
    return _run("campaign", payload, max_tokens=2500)
