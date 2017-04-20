import random
import re
from itertools import zip_longest


def split_utf8(text, max_length):
    """Split UTF-8 s into chunks of maximum length n."""
    # From http://stackoverflow.com/a/6043797/1524507
    # Modified for Python 3
    byte_string = text.encode('utf8')
    while len(byte_string) > max_length:
        k = max_length
        while (byte_string[k] & 0xc0) == 0x80:
            k -= 1
        yield byte_string[:k].decode('utf8')
        byte_string = byte_string[k:]
    yield byte_string.decode('utf8')


def weighted_choice(choices):
    # http://stackoverflow.com/a/3679747/1524507
    total = sum(w for c, w in choices)
    r = random.uniform(0, total)
    upto = 0
    for c, w in choices:
        if upto + w >= r:
            return c
        upto += w
    assert False, "Shouldn't get here"


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


def escape_links(text: str) -> str:
    return re.sub(r'\b(https?\S+)', '<\g<1>>', text)
