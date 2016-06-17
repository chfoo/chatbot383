import os
import unittest

import collections

from chatbot383.featurecomponents.battlebot import BattleBot, BattleState

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

        self.assertEqual(BattleState.idle, battle_bot.state)

        battle_bot._parse_text(
            'You have been challenged to a Pokemon Battle by TestUser! '
            'To accept, go to the Battle Dungeon and type !accept. '
            'You have one minute.'
        )
        self.assertTrue(bot.last_text[1].startswith('G'))
        self.assertEqual('!accept', bot.last_whisper[1])
        self.assertEqual(BattleState.in_battle, battle_bot.state)

        bot.last_text = None

        battle_bot._parse_text(
            'BotUsername sends out Tentacool (Level 97)! TestUser sends '
            'out Nidorina (Level 97)!'
        )
        self.assertEqual(
            30,
            battle_bot.session.opponent_pokemon.dex_info.species_id
        )

        move_counter = collections.Counter()

        for dummy in range(100):
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
            move_counter[bot.last_whisper[1]] += 1

        self.assertTrue('!move2', move_counter.most_common()[0][0])

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

        self.assertTrue(bot.last_text[1].startswith('G'))
        self.assertEqual(BattleState.idle, battle_bot.state)

    def test_no_moves(self):
        bot = MockBot()
        battle_bot = BattleBot(POKEDEX, bot)

        self.assertEqual(BattleState.idle, battle_bot.state)

        battle_bot._parse_text(
            'You have been challenged to a Pokemon Battle by TestUser! '
            'To accept, go to the Battle Dungeon and type !accept. '
            'You have one minute.'
        )
        battle_bot._parse_text(
            'BotUsername sends out Farfetch\'d (Level 97)! TestUser sends '
            'out Gastly (Level 97)!'
        )
        self.assertEqual(
            92,
            battle_bot.session.opponent_pokemon.dex_info.species_id
        )

        move_counter = collections.Counter()

        for dummy in range(100):
            battle_bot._parse_text(
                'What will Farfetch\'d do? '
                '(!move1)Slash, (!move2)Feint, (!move3)Fury Attack, '
                '(!move4)Leer (!help)Additional Commands '
                '(reply in Battle Dungeon)'
            )
            self.assertIn(
                bot.last_whisper[1],
                ('!move1', '!move2', '!move3', '!move4')
            )
            move_counter[bot.last_whisper[1]] += 1

        self.assertTrue(move_counter['!move1'])
        self.assertTrue(move_counter['!move2'])
        self.assertTrue(move_counter['!move3'])
        self.assertTrue(move_counter['!move4'])

    def test_pwt_loser(self):
        self._pwt_iteration('loser')

    def test_pwt_winner(self):
        self._pwt_iteration('winner')

    def _pwt_iteration(self, iteration: str):
        bot = MockBot()
        battle_bot = BattleBot(POKEDEX, bot)

        self.assertEqual(BattleState.idle, battle_bot.state)

        battle_bot._parse_text(
            'BlahUserName has started a new Random Pokemon World Tournament!'
            ' Type !join to join. The PWT will start in 60 seconds.'
        )

        self.assertIsNone(bot.last_text)
        self.assertIsNone(bot.last_whisper)

        battle_bot._parse_text(
            'TestUser has been added to the PWT! Type !join to join.'
        )

        self.assertIsNone(bot.last_text)
        self.assertIsNone(bot.last_whisper)

        def not_us():
            battle_bot._parse_text(
                'This is a First Round match of the Random tournament! '
                'This match is between Pro Memer TestUser and Gambler Spencer!'
            )

            self.assertIsNone(bot.last_text)
            self.assertIsNone(bot.last_whisper)

            battle_bot._parse_text('Blah blah copypasta')

            self.assertIsNone(bot.last_text)
            self.assertIsNone(bot.last_whisper)

            battle_bot._parse_text('TestUser forfeits! Gambler Spencer wins!')

            self.assertIsNone(bot.last_text)
            self.assertIsNone(bot.last_whisper)

        not_us()

        if iteration == 'loser':
            battle_bot._parse_text(
                'This is a First Round match of the Random tournament! '
                'This match is between TestUser and Groudonger!'
            )
        else:
            battle_bot._parse_text(
                'This is a First Round match of the Random tournament! '
                'This match is between Pro Memer TestUser and Gym Leader Groudonger!'
            )

        self.assertEqual(BattleState.in_pwt_battle, battle_bot.state)
        self.assertTrue(bot.last_text[1].startswith('G'))

        bot.last_text = None

        battle_bot._parse_text(
            'Gym Leader Groudonger sends out Tentacool (Level 97)! '
            'TestUser sends out Nidorina (Level 97)!'
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

        if iteration == 'loser':
            battle_bot._parse_text(
                'Gym Leader Groudonger is out of usable Pokemon! '
                'TestUser wins! PogChamp'
            )
        else:
            battle_bot._parse_text(
                'TestUser is out of usable Pokemon! '
                'Gym Leader Groudonger wins! PogChamp'
            )

        self.assertEqual(BattleState.in_pwt_standby, battle_bot.state)
        self.assertTrue(bot.last_text[1].startswith('G'))

        bot.last_text = None
        bot.last_whisper = None

        not_us()

        if iteration == 'loser':
            battle_bot._parse_text(
                'Scientist Tim has won the Random Pokemon World Tournament! PagChomp'
            )

            self.assertIsNone(bot.last_text)
        else:
            battle_bot._parse_text(
                'Gym Leader Groudonger has won the Random Pokemon World Tournament! PagChomp'
            )
            self.assertTrue(bot.last_text[1].startswith('G'))

            bot.last_text = None

        self.assertEqual(BattleState.idle, battle_bot.state)


