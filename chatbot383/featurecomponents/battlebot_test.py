import os
import unittest

from chatbot383.featurecomponents.battlebot import BattleBot


POKEDEX = os.environ.get('POKEDEX', 'veekun_pokedex.sqlite')


class MockBot(object):
    def __init__(self):
        self.last_whisper = None
        self.last_text = None

    def send_whisper(self, username, text, allow_command_prefix=True):
        print('->', username, text)
        self.last_whisper = username, text

    def send_text(self, channel, text):
        print('=>', channel, text)
        self.last_text = channel, text


class TestBattleBot(unittest.TestCase):
    def test_battle(self):
        bot = MockBot()
        battle_bot = BattleBot(POKEDEX, bot)

        battle_bot._parse_text(
            'You have been challenged to a Pokemon Battle by TestUser! '
            'To accept, go to the Battle Dungeon and type !accept. '
            'You have one minute.'
        )
        self.assertEqual('!accept', bot.last_whisper[1])

        battle_bot._parse_text(
            'BotUsername sends out Tentacool (Level 97)! TestUser sends '
            'out Nidorina (Level 97)!'
        )
        self.assertEqual(
            30,
            battle_bot.session.opponent_pokemon.dex_info.species_id
        )

        battle_bot._parse_text(
            'What will Tentacool do? '
            '(!move1)Icy-wind, (!move2)Water-gun, (!move3)Acid, '
            '(!move4)Knock-off (!help)Additional Commands '
            '(reply in Battle Dungeon)'
        )
        self.assertIn(
            bot.last_whisper[1],
            ('!move1', '!move2', '!move3', '!move4')
        )

        battle_bot._parse_text(
            'Type !list to get a list of your Pokemon. Type !switch<number> '
            'to switch to that Pokemon (for example, the if you want to '
            'switch to the first Pokemon, type !switch0'
        )
        self.assertEqual('!switch0', bot.last_whisper[1])

        battle_bot._parse_text(
            'TestUser calls back Nidorina and sent out Basculin!'
        )
        self.assertEqual(
            550,
            battle_bot.session.opponent_pokemon.dex_info.species_id
        )

        battle_bot._parse_text(
            'TestUser is out of usable Pokemon! Trainer Class '
            'BotUsername wins! PogChamp'
        )
