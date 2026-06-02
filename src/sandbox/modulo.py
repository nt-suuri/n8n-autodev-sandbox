def modulo(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError("modulo by zero")
    return a % b
