DEBUG_PRINTS = True


def debug_print(*args, **kwargs) -> None:
    if DEBUG_PRINTS:
        print(*args, **kwargs)
