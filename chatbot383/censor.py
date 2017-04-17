import re

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


def censor_text(text: str) -> str:
    return NAUGHTY_REGEX.sub('***', text)


if __name__ == '__main__':
    while True:
        print(censor_text(input('>')))
