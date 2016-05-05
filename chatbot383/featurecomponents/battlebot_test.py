import os
import unittest

from chatbot383.featurecomponents.battlebot import BattleBot


POKEDEX = os.environ.get('POKEDEX', 'veekun_pokedex.sqlite')


class MockBot(object):
    def send_whisper(self, username, text, allow_command_prefix=True):
        print('->', username, text)

    def send_text(self, channel, text):
        print('=>', channel, text)


class TestBattleBot(unittest.TestCase):
    def test_battle(self):
        battle_bot = BattleBot(POKEDEX, MockBot())

        battle_bot._parse_text(
            'You have been challenged to a Pokemon Battle by TestUser! '
            'To accept, go to the Battle Dungeon and type !accept. '
            'You have one minute.'
        )
        battle_bot._parse_text(
            'BotUsername sends out Tentacool (Level 97)! TestUser sends '
            'out Nidorina (Level 97)!'
        )
        battle_bot._parse_text(
            'What will Tentacool do? '
            '(!move1)Icy-wind, (!move2)Water-gun, (!move3)Acid, '
            '(!move4)Knock-off (!help)Additional Commands '
            '(reply in Battle Dungeon)'
        )
        battle_bot._parse_text(
            'Type !list to get a list of your Pokemon. Type !switch<number> '
            'to switch to that Pokemon (for example, the if you want to '
            'switch to the first Pokemon, type !switch0'
        )
        battle_bot._parse_text(
            'TestUser is out of usable Pokemon! Trainer Class '
            'BotUsername wins! PogChamp'
        )
