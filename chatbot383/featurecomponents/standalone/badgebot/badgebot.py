import argparse
import enum
import json
import logging
import random
import re
import ssl
import logging.handlers
import collections
import time

import irc.client
import irc.strings
import irc.connection
import sqlite3

import math

import unicodedata

_logger = logging.getLogger(__name__)

IRC_RATE_LIMIT = (20 - 0.5) / 30
RECONNECT_MIN_INTERVAL = 4
RECONNECT_MAX_INTERVAL = 300


BALANCE_PATTERN = re.compile(r'you have P(\d+) pokeyen( \(P\d+ reserved\))? T(\d+) tokens?( \(T\d+ reserved\))?')
PENDING_SELL_ORDER_PREFIX = 'Selling badges'
PENDING_BUY_ORDER_PREFIX = 'Buying badges:'
BADGES_PREFIX = 'your badges:'
ORDER_ITEM_PATTERN = re.compile(r'(.+) T(\d+)x(\d+)')
BADGES_PATTERN = re.compile(r'(\d+)x #(\d+) (.+)')
CANCEL_SELL_ORDER_PATTERN = re.compile(r'cancelled the selling of (\d+) (.+) badge\(s\)')
CANCEL_BUY_ORDER_PATTERN = re.compile(r'cancelled (\d+) offer to buy (\d+) (.+) badge\(s\) for T(\d+)')
BADGE_PRICE = re.compile(r'(\d+) (.+) badge\(s\) available, cheapest is T(\d+)')
BADGE_NO_PRICE = re.compile(r'no (.+) badges available to purchase( for T(\d+))?')
PURCHASED_BADGE_PATTERN = re.compile(r'you purchased a (.+) badge for T(\d+) from @(.+)')
SELL_ORDER_POSTED_PATTERN = re.compile(r'(.+) badge put up for sale for T(\d+) tokens')
SELL_ORDER_COMPLETE_PATTERN = re.compile(r'you sold a (.+) badge for T(\d+) to @(.+)')
BUY_ORDER_POSTED_PATTERN = re.compile(r'made an offer to buy (\d+) (.+) badge at T(\d+) each \(expires in (\d+) hours\)')
NO_BUY_ORDERS_PENDING = 'No offers to buy badges'
NO_SELL_ORDERS_PENDING = 'Not selling any badges'
BADGE_RARITY_PATTERN = re.compile(r'#(\d+) (.+) badges existing: (\d+) ?.*')

OrderInfo = collections.namedtuple('OrderInfo', ['pokemon_name', 'species_id', 'price', 'amount'])
ValuePending = object()


class TPPBotFacade(object):
    def __init__(self, client: 'Client'):
        self._client = client

    def check_badges(self):
        self._send_tpp_bot_whisper('badges')

    def check_badge_rarity(self, pokemon_name):
        self._send_tpp_bot_whisper('checkbadge {}'.format(pokemon_name))

    def check_badge_price(self, pokemon_name):
        if ' ' in pokemon_name:
            raise ValueError()

        self._send_tpp_bot_whisper('buybadge {}'.format(pokemon_name))

    def check_buy_orders(self):
        self._send_tpp_bot_whisper('listbuybadge')

    def check_sell_orders(self):
        self._send_tpp_bot_whisper('listsellbadge')

    def cancel_sell_order(self, pokemon_name):
        self._send_tpp_bot_whisper('cancelsellbadge {}'.format(pokemon_name))

    def cancel_buy_order(self, pokemon_name):
        self._send_tpp_bot_whisper('cancelbuybadge {}'.format(pokemon_name))

    def buy_badge(self, pokemon_name, price=1, duration='7d'):
        if ' ' in pokemon_name:
            raise ValueError()

        assert 1 <= price <= 10000

        self._send_tpp_bot_whisper(
            'buybadge {pokemon_name} t{price} {duration}'.format(
                pokemon_name=pokemon_name,
                price=price,
                duration=duration
            ))

    def sell_badge(self, pokemon_name, price=10000):
        if ' ' in pokemon_name:
            raise ValueError()

        assert 1 <= price <= 10000

        self._send_tpp_bot_whisper(
            'sellbadge {pokemon_name} t{price}'.format(
                pokemon_name=pokemon_name,
                price=price,
            ))

    def check_balance(self):
        self._send_tpp_bot_whisper('balance')

    def _send_tpp_bot_whisper(self, command):
        _logger.info('Command: %s', command)
        self._client.connection.privmsg('#jtv', '.w tpp {}'.format(command))


@enum.unique
class BotState(enum.Enum):
    idle = 'idle'

    populate_account_details = 'populate_account_details'
    cancel_orders = 'cancel_orders'
    selling = 'selling'
    buying = 'buying'


class BadgeBot(object):
    # \/ Please adjust these:
    MIN_BALANCE = 150  # minimum number of tokens to do anything
    BUY_MAX_PRICE = 5  # maximum number of tokens to spend on buying
    # /\

    def __init__(self, tpp_bot: TPPBotFacade, database_path: str):
        self._tpp_bot = tpp_bot
        self._pending_sell_orders = {}
        self._pending_buy_orders = {}
        self._badges = {}
        self._token_balance = 0
        self._db_con = sqlite3.connect(database_path)
        self._state = BotState.idle

        self._prev_message = None

    @property
    def token_balance(self) -> int:
        return self._token_balance

    @property
    def badges(self) -> dict:
        return self._badges

    @property
    def pending_sell_orders(self) -> dict:
        return self._pending_sell_orders

    @property
    def pending_buy_orders(self) -> dict:
        return self._pending_buy_orders

    def _set_state(self, state):
        _logger.info('Set state %s', state)
        self._state = state

    def populate_account_details(self):
        if self._state != BotState.idle:
            _logger.warning('Cannot populate account. State not idle. Got %s', self._state)
            return

        self._set_state(BotState.populate_account_details)
        self._tpp_bot.check_balance()
        self._tpp_bot.check_badges()
        self._tpp_bot.check_buy_orders()
        self._tpp_bot.check_sell_orders()

    def process_text(self, text: str):
        # Join multiline messages
        if text.endswith(' ...'):
            if self._prev_message:
                self._prev_message += text.replace(' ...', ', ')
            else:
                self._prev_message = text.replace(' ...', ', ')

            return

        if self._prev_message:
            text = self._prev_message + text
            self._prev_message = None

        _logger.debug('Process text: %s', text)

        balance_match = BALANCE_PATTERN.match(text)

        if balance_match:
            self._set_token_balance(int(balance_match.group(3)))

        elif text.startswith(BADGES_PREFIX):
            self._badges = self._parse_badges_list(
                text.split(':', 1)[1]
            )

        elif text.startswith(PENDING_BUY_ORDER_PREFIX):
            self._pending_buy_orders = self._parse_order_list(text.split(':', 1)[1])

        elif text.startswith(NO_BUY_ORDERS_PENDING):
            self._pending_buy_orders = {}

        elif text.startswith(PENDING_SELL_ORDER_PREFIX):
            self._pending_sell_orders = self._parse_order_list(text.split(':', 1)[1])

            if self._state == BotState.populate_account_details:
                self._set_state(BotState.cancel_orders)
                self._cancel_orders()

        elif text.startswith(NO_SELL_ORDERS_PENDING):
            self._pending_sell_orders = {}

            if self._state == BotState.populate_account_details:
                self._set_state(BotState.cancel_orders)
                self._cancel_orders()

        elif CANCEL_BUY_ORDER_PATTERN.match(text):
            match = CANCEL_BUY_ORDER_PATTERN.match(text)
            pokemon_name = match.group(3)
            species_id = self.look_up_species_id(pokemon_name)
            if species_id in self._pending_buy_orders:
                del self._pending_buy_orders[species_id]

            if not self._pending_buy_orders and self._state == BotState.cancel_orders:
                self._set_state(BotState.idle)

        elif CANCEL_SELL_ORDER_PATTERN.match(text):
            match = CANCEL_SELL_ORDER_PATTERN.match(text)
            pokemon_name = match.group(2)
            species_id = self.look_up_species_id(pokemon_name)
            if species_id in self._pending_sell_orders:
                del self._pending_sell_orders[species_id]

            if not self._pending_sell_orders and self._state == BotState.cancel_orders:
                self._set_state(BotState.idle)

        elif BADGE_RARITY_PATTERN.match(text):
            match = BADGE_RARITY_PATTERN.match(text)
            species_id = int(match.group(1))
            num_available = int(match.group(3))

            if self._state == BotState.buying:
                self._process_and_buy(species_id, num_available)
            elif self._state == BotState.selling:
                self._process_and_sell(species_id, num_available)

        elif PURCHASED_BADGE_PATTERN.match(text):
            if self._state == BotState.buying:
                self._set_state(BotState.idle)

        elif SELL_ORDER_COMPLETE_PATTERN.match(text):
            if self._state == BotState.selling:
                self._set_state(BotState.idle)

        elif BUY_ORDER_POSTED_PATTERN.match(text):
            match = BUY_ORDER_POSTED_PATTERN.match(text)

            amount = int(match.group(1))
            pokemon_name = self.slugify(match.group(2))
            price = int(match.group(3))
            species_id = self.look_up_species_id(pokemon_name)

            self._pending_buy_orders[species_id] = OrderInfo(
                pokemon_name,
                species_id,
                price,
                amount
            )

        elif SELL_ORDER_POSTED_PATTERN.match(text):
            match = SELL_ORDER_POSTED_PATTERN.match(text)

            pokemon_name = self.slugify(match.group(1))
            price = int(match.group(2))
            species_id = self.look_up_species_id(pokemon_name)
            amount = 1

            self._pending_sell_orders[species_id] = OrderInfo(
                pokemon_name,
                species_id,
                price,
                amount
            )

    def cancel_and_reset(self):
        _logger.info('Resetting')
        self._set_state(BotState.idle)
        self.populate_account_details()

    def begin_trading(self, trade_type=None):
        if self._state != BotState.idle:
            _logger.warning('Cannot trade. State not idle. Got %s', self._state)
            return

        if self._token_balance <= self.MIN_BALANCE:
            _logger.info('Not enough tokens.')
            return

        # if not trade_type and random.random() < 0.5 or trade_type == 'buy':
        if False:
            self._set_state(BotState.buying)
            species_id = random.randint(152, 721)
        else:
            if not self._badges:
                _logger.info('No badges to sell')
                return

            self._set_state(BotState.selling)

            species_id = random.choice(tuple(self._badges.keys()))

        pokemon_name = self.look_up_pokemon_name(species_id)

        _logger.info('Want to trade %s %s', species_id, pokemon_name)

        self._tpp_bot.check_badge_rarity(pokemon_name)

    def _process_and_sell(self, species_id: int, num_available: int):
        assert num_available > 0

        if num_available <= 100:
            price = max(2, math.ceil(300 * 1 / math.sqrt((num_available + 1.2) * 2) - 8)) + random.choice([0, 0, 0, 0, 1, 2])
        else:
            price = max(2, math.ceil(500 * 1 / math.sqrt((num_available + 0.4) * 6) - 10))
        assert price > 0
        if num_available < 4:
            assert price > 80
        if num_available < 10:
            assert price > 50

        pokemon_name = self.look_up_pokemon_name(species_id)

        _logger.info('Sell badge %s %s for %s', species_id, pokemon_name, price)
        self._tpp_bot.sell_badge(pokemon_name, price)

    def _process_and_buy(self, species_id: int, num_available: int):
        if num_available == 0:
            price = 1
        else:
            price = max(1, math.ceil(200 * 1 / math.sqrt(num_available * 5) - 5))

        assert price > 0

        pokemon_name = self.look_up_pokemon_name(species_id)

        if price > self.BUY_MAX_PRICE:
            _logger.info('Badge to expensive to buy %s %s for %s', species_id, pokemon_name, price)
            return

        _logger.info('Buy badge %s %s for %s', species_id, pokemon_name, price)

        assert price <= self.BUY_MAX_PRICE

        self._tpp_bot.buy_badge(pokemon_name, price)

    def _set_token_balance(self, tokens: int):
        assert isinstance(tokens, int), type(tokens)
        _logger.info('Update token balance to %s', tokens)
        self._token_balance = tokens

    def _parse_order_list(self, text: str) -> dict:
        items = text.split(',')
        orders = {}

        for item in items:
            item = item.strip()
            match = ORDER_ITEM_PATTERN.match(item)
            pokemon_name = self.slugify(match.group(1))
            price = int(match.group(2))
            amount = int(match.group(3))
            species_id = self.look_up_species_id(pokemon_name)

            orders[species_id] = OrderInfo(
                pokemon_name,
                species_id,
                price,
                amount
            )

        return orders

    def _parse_badges_list(self, text: str) -> dict:
        badges = {}
        items = text.split(',')

        for item in items:
            item = item.strip()
            match = BADGES_PATTERN.match(item)

            amount = int(match.group(1))
            species_id = int(match.group(2))

            badges[species_id] = amount

        return badges

    def _cancel_orders(self):
        _logger.info('Cancelling orders')

        if not self._pending_buy_orders and not self._pending_sell_orders:
            self._set_state(BotState.idle)

        if self._pending_buy_orders:
            for order_info in self._pending_buy_orders.values():
                pokemon_name = order_info.pokemon_name
                _logger.info('Cancel buy %s', pokemon_name)
                self._tpp_bot.cancel_buy_order(pokemon_name)

        if self._pending_sell_orders:
            for order_info in self._pending_sell_orders.values():
                pokemon_name = order_info.pokemon_name
                _logger.info('Cancel sell %s', pokemon_name)
                self._tpp_bot.cancel_sell_order(pokemon_name)

        _logger.info('Cancel order finished')

    def look_up_species_id(self, pokemon_name: str) -> int:
        slug = self.slugify(pokemon_name, no_dash=True)

        row = self._db_con.execute(
            '''
            SELECT species_id
            FROM pokemon
            WHERE replace(identifier, '-', '') LIKE ?
            ''',
            ('{}%'.format(slug),)
        ).fetchone()

        return row[0]

    def look_up_pokemon_name(self, species_id: int) -> str:
        row = self._db_con.execute(
            '''
            SELECT identifier
            FROM pokemon
            WHERE species_id = ?
            ''',
            (species_id,)
        ).fetchone()

        return row[0]

    @classmethod
    def slugify(cls, text, no_dash=False):
        text = text.lower() \
            .replace('♀', 'f') \
            .replace('♂', 'm') \
            .replace(' ', '-')

        if no_dash:
            text = text.replace('-', '')

        text = cls.remove_accents(text)
        text = re.sub(r'[^a-zA-Z-]', '', text)
        return text

    @classmethod
    def remove_accents(cls, input_str):
        # http://stackoverflow.com/a/517974/1524507
        nfkd_form = unicodedata.normalize('NFKD', input_str)
        return "".join([c for c in nfkd_form if not unicodedata.combining(c)])


TRADING_INTERVAL = 30  # in minutes, on the minute. how often to schedule trading


class Client(irc.client.SimpleIRCClient):
    def __init__(self, database_path: str):
        super().__init__()

        irc.client.ServerConnection.buffer_class.errors = 'replace'
        self.connection.set_rate_limit(IRC_RATE_LIMIT)
        self._reconnect_interval = RECONNECT_MIN_INTERVAL
        self._running = True
        self._tpp_bot_facade = TPPBotFacade(self)
        self._badge_bot = BadgeBot(self._tpp_bot_facade, database_path)

        self.reactor.execute_every(300, self._keep_alive)
        self.reactor.execute_at(get_next_on_the_minute(TRADING_INTERVAL) - 30, self._trigger_trading)

    def _keep_alive(self):
        if self.connection.is_connected():
            self.connection.ping('keep-alive')

    def autoconnect(self, *args, **kwargs):
        _logger.info('Connecting %s...', args[:2] or self.connection.server_address)
        try:
            if args:
                self.connect(*args, **kwargs)
            else:
                self.connection.reconnect()
        except irc.client.ServerConnectionError:
            _logger.exception('Connect failed.')
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        self.reactor.execute_delayed(self._reconnect_interval, self.autoconnect)
        self._reconnect_interval *= 2
        self._reconnect_interval = min(RECONNECT_MAX_INTERVAL, self._reconnect_interval)

    def on_disconnect(self, connection, event):
        _logger.info('Disconnected %s!', self.connection.server_address)

        if self._running:
            self._schedule_reconnect()

    def stop(self):
        self._running = False
        self.reactor.disconnect_all()

    def on_welcome(self, connection, event):
        _logger.info('Logged in to server %s.', self.connection.server_address)
        self.connection.cap('REQ', 'twitch.tv/membership')
        self.connection.cap('REQ', 'twitch.tv/commands')
        self.connection.cap('REQ', 'twitch.tv/tags')

        self._reconnect_interval = RECONNECT_MIN_INTERVAL

        connection.join('#twitchplayspokemon')

        self._badge_bot.populate_account_details()

    def on_pubmsg(self, connection, event):
        self._process_message(event)

    def on_action(self, connection, event):
        self._process_message(event)

    def on_whisper(self, connection, event):
        username = irc.strings.lower(event.source.nick)
        text = event.arguments[0]

        if username != 'tpp':
            return

        _logger.info('tpp (w): %s', text)

        self._badge_bot.process_text(text)

    def _process_message(self, event):
        username = irc.strings.lower(event.source.nick)

        if not event.arguments:
            return

        if username != 'tpp':
            return

        text = event.arguments[0]

        _logger.info('tpp: %s', text)

    def _trigger_trading(self):
        if not self.connection.is_connected():
            return

        self._badge_bot.cancel_and_reset()

        self.reactor.execute_delayed(30, self._badge_bot.begin_trading)

        def sched():
            self.reactor.execute_at(get_next_on_the_minute(TRADING_INTERVAL) - 30, self._trigger_trading)

        self.reactor.execute_delayed(10, sched)


def get_next_on_the_minute(minute: int):
    current_time = int(time.time())
    return current_time - current_time % (minute * 60) + minute * 60


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('config_file', type=argparse.FileType('r'))

    args = arg_parser.parse_args()
    config = json.load(args.config_file)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=[
            logging.handlers.TimedRotatingFileHandler(config['log_file'], when='midnight', utc=True),
            logging.StreamHandler(),
        ]
    )

    client = Client(config['pokedex_database'])
    client.autoconnect(
        'irc.chat.twitch.tv',
        6697,
        nickname=config['username'],
        password=config['password'],
        connect_factory=irc.connection.Factory(wrapper=ssl.wrap_socket)
    )

    try:
        client.reactor.process_forever()
    except Exception:
        _logger.exception('Fatal error')
        raise

if __name__ == '__main__':
    main()
