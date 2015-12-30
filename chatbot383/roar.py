import random

CHAINS = {
    None: ('G',),
    'G': ('r', 'u'),
    'r': ('r', 'r', 'g', 'a', 'o'),
    'g': ('g', 'r'),
    'a': ('h',),
    'o': ('o', 'o', 'u'),
    'u': ('u', 'u', 'r', 'r', 'h'),
    'h': ('!', 'h'),
    '!': (None, '!'),
}


def make_chain():
    current = None
    chars = []

    while True:
        next_choices = CHAINS[current]

        next_choice = random.choice(next_choices)

        if not next_choice:
            break

        chars.append(next_choice)
        current = next_choice

    return ''.join(chars)


def gen_roar():
    while True:
        text = make_chain()
        if 8 < len(text) < 30:
            return text


if __name__ == '__main__':
    for dummy in range(20):
        print(gen_roar())
