import os
import unittest

from badgebot import TPPBotFacade, BadgeBot

POKEDEX = os.environ.get('POKEDEX', 'veekun_pokedex.sqlite')


class MockTPPBotFacade(TPPBotFacade):
    def __init__(self):
        self.commands = []
        self.prev_command = None

    def _send_tpp_bot_whisper(self, command):
        print("whisper -> tpp:", command)
        self.commands.append(command)
        self.prev_command = command


class TestBadgeBot(unittest.TestCase):
    def test_bot_stuff(self):
        tpp_bot_facade = MockTPPBotFacade()
        badge_bot = BadgeBot(tpp_bot_facade, POKEDEX)

        badge_bot.populate_account_details()

        # Test start up

        sent_command = tpp_bot_facade.commands.pop(0)
        self.assertEqual('balance', sent_command)

        badge_bot.process_text('you have P100 pokeyen T500 tokens')

        self.assertEqual(500, badge_bot.token_balance)

        sent_command = tpp_bot_facade.commands.pop(0)
        self.assertEqual('badges', sent_command)

        badge_bot.process_text('your badges: 1x #001 Bulbasaur, 3x #004 Charmander ...')
        badge_bot.process_text('1x #007 Squirtle')

        sent_command = tpp_bot_facade.commands.pop(0)
        self.assertEqual('listbuybadge', sent_command)

        badge_bot.process_text('Buying badges: Chatot T1x1, Entei T1x1')

        sent_command = tpp_bot_facade.commands.pop(0)
        self.assertEqual('listsellbadge', sent_command)

        badge_bot.process_text('Selling badges: Rattata T10000x1')

        self.assertEqual(2, len(badge_bot.pending_buy_orders))
        self.assertEqual(1, len(badge_bot.pending_sell_orders))

        sent_command = tpp_bot_facade.commands.pop(0)
        self.assertRegex(sent_command, 'cancelbuybadge .+')

        badge_bot.process_text('cancelled 1 offer to buy 1 Chatot badge(s) for T1')

        sent_command = tpp_bot_facade.commands.pop(0)
        self.assertRegex(sent_command, 'cancelbuybadge .+')

        badge_bot.process_text('cancelled 1 offer to buy 1 Entei badge(s) for T1')

        sent_command = tpp_bot_facade.commands.pop(0)
        self.assertRegex(sent_command, 'cancelsellbadge rattata')

        badge_bot.process_text('cancelled the selling of 1 Rattata badge(s)')

        self.assertFalse(badge_bot.pending_buy_orders)
        self.assertFalse(badge_bot.pending_sell_orders)

        # Test buy trading

        badge_bot.begin_trading(trade_type='buy')

        sent_command = tpp_bot_facade.commands.pop(0)
        pokemon_name = sent_command.split()[1]
        species_id = badge_bot.look_up_species_id(pokemon_name)

        badge_bot.process_text('#{} {} badges existing: 100'.format(species_id, pokemon_name))

        sent_command = tpp_bot_facade.commands.pop(0)
        price = int(sent_command.split()[2].strip('t'))

        badge_bot.process_text('made an offer to buy 1 {} badge at T{} each (expires in 168 hours)'.format(pokemon_name, price))

        self.assertEqual(1, len(badge_bot.pending_buy_orders))

        # Test reset

        badge_bot.cancel_and_reset()

        badge_bot.process_text('you have P100 pokeyen T500 tokens')
        badge_bot.process_text('your badges: 1x #001 Bulbasaur, 3x #004 Charmander ...')
        badge_bot.process_text('1x #007 Squirtle')
        badge_bot.process_text('No offers to buy badges')
        badge_bot.process_text('Not selling any badges')

        self.assertFalse(badge_bot.pending_buy_orders)
        self.assertFalse(badge_bot.pending_sell_orders)

        tpp_bot_facade.commands.clear()

        # Test sell trading

        badge_bot.begin_trading(trade_type='sell')

        sent_command = tpp_bot_facade.commands.pop(0)
        pokemon_name = sent_command.split()[1]
        species_id = badge_bot.look_up_species_id(pokemon_name)

        badge_bot.process_text('#{} {} badges existing: 100'.format(species_id, pokemon_name))

        sent_command = tpp_bot_facade.commands.pop(0)
        price = int(sent_command.split()[2].strip('t'))

        badge_bot.process_text('{} badge put up for sale for T{} tokens'.format(pokemon_name, price))

        self.assertEqual(1, len(badge_bot.pending_sell_orders))
