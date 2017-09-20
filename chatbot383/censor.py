import re
import urllib.parse


NAUGHTY_WORDS = tuple('''
anal
anus
arse
ass
ballsack
balls
bastard
bitch
biatch
bloody
blowjob
bollock
bollok
boner
boob
bugger
bum
butt
buttplug
clitoris
cock
coon
crap
cunt
damn
dick
dildo
dyke
fag
feck
fellate
fellatio
felching
fuck
fudgepacker
flange
Goddamn
hell
homo
jerk
jizz
knobend
labia
lmao
lmfao
muff
nigger
nigga
omg
penis
piss
poop
prick
pube
pussy
queer
scrotum
sex
shit
sh1t
slut
smegma
spunk
tit
tosser
turd
twat
vagina
wank
whore
wtf
'''.split())

NAUGHTY_REGEX = re.compile(
    '|'.join(
        r'\b{}\b'.format(re.escape(word)) for word in NAUGHTY_WORDS
    ),
    re.IGNORECASE
)

SUBSTRING_NAUGHTY_REGEX = re.compile(
    '|'.join(
        re.escape(word) for word in NAUGHTY_WORDS
    ),
    re.IGNORECASE
)


LINK_WHITELIST = frozenset([
    '.twitch.tv',
])


def censor_text(text: str) -> str:
    return NAUGHTY_REGEX.sub('***', text)


def is_link_whitelisted(link: str) -> bool:
    if not link.startswith('http'):
        link = 'http://{}'.format(link)

    result = urllib.parse.urlparse(link)
    hostname = result.hostname or ''  # type:str

    if not hostname:
        return False

    for whitelist_part in LINK_WHITELIST:
        if hostname.endswith(whitelist_part) \
                or '.{}'.format(hostname) == whitelist_part:
            return True

    return False


def censor_link(text: str) -> str:
    def _regex_callback(match):
        link = match.group(2)

        if is_link_whitelisted(link):
            return '{}{}'.format(match.group(1), match.group(2))
        else:
            shibe = '<:PancakeShibe:349613344572833815>'
            return '{}<naughty link {}>'.format(
                match.group(1),
                SUBSTRING_NAUGHTY_REGEX.sub(shibe, match.group(2), 2).replace('.', shibe, 2)
            )

    return re.sub(r'(\s|^)((?:https?\S+)|(?:\S+\.[a-zA-Z]{1,10}\S*))', _regex_callback, text)


if __name__ == '__main__':
    while True:
        print(censor_text(input('>')))
