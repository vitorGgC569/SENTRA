"""Bounded host-owned gestures: cleanup stays with the admitted effect."""


def chord_scancodes(arguments):
    keys = arguments.get('keys')
    if set(arguments) != {'action', 'keys'} or not isinstance(keys, list) or not 1 <= len(keys) <= 8:
        raise ValueError('bounded atomic keyboard chord required')
    for key in keys:
        if (not isinstance(key, list) or len(key) not in (1, 2)
                or (len(key) == 2 and key[0] != 224)
                or type(key[-1]) is not int or not 1 <= key[-1] <= 127):
            raise ValueError('physical make scancodes required')
    return ([code for key in keys for code in key],
            [code for key in reversed(keys) for code in [*key[:-1], key[-1] | 128]])


def drag_points(arguments):
    points = arguments.get('points')
    if set(arguments) != {'action', 'points'} or not isinstance(points, list) or not 2 <= len(points) <= 32:
        raise ValueError('bounded atomic pointer drag required')
    if any(not isinstance(point, list) or len(point) != 2 or
           any(type(value) is not int or not 1 <= value <= 8192 for value in point) for point in points):
        raise ValueError('bounded framebuffer drag points required')
    return points
