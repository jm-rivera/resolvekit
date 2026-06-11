"""Shared Latin-script filter for calibration adapters."""


def is_latin_recoverable(name: str) -> bool:
    """Check if a name is primarily Latin-script and likely recoverable."""
    alpha_count = non_latin = 0
    for c in name:
        if c.isalpha():
            alpha_count += 1
            if ord(c) > 0x024F:
                non_latin += 1
    if not alpha_count:
        return False
    return non_latin / alpha_count < 0.2
