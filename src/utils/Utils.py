import random

def generate_random_float(min_value: float, max_value: float) -> float:
    """Generate a random float between min_value and max_value.

    Args:
        min_value: Lower bound of the range (inclusive).
        max_value: Upper bound of the range (inclusive).

    Returns:
        A pseudo-random float sampled uniformly from
        [min_value, max_value].

    Raises:
        Never raises; delegates directly to random.uniform, which
        does not validate that min_value <= max_value.
    """
    return random.uniform(min_value, max_value)
