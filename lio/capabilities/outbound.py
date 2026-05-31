from ._runner import run as _run


def run(payload: dict) -> dict:
    return _run("outbound", payload, max_tokens=3000)
