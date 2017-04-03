import argparse
import datetime
import enum
import json
import logging
import random
import re
import ssl
import logging.handlers
import time

import irc.client
import irc.strings
import irc.connection

_logger = logging.getLogger(__name__)

IRC_RATE_LIMIT = (20 - 0.5) / 30
RECONNECT_MIN_INTERVAL = 4
RECONNECT_MAX_INTERVAL = 300


class BattleState(enum.Enum):
    waiting = 'waiting'
    betting = 'betting'
    battle = 'battle'
    finished = 'finished'


class TPPBotFacade(object):
    def __init__(self, client: 'Client'):
        self._client = client

    def place_buy_order(self, team: str, price: int=1, amount: int=1, duration: int=1):
        assert isinstance(team, str), type(team)
        assert isinstance(price, int), type(price)
        assert isinstance(amount, int), type(amount)
        assert isinstance(duration, int), type(duration)

        command = 'order buy {team} t{price} {amount} {duration}m'.format(
            team=team, price=price, amount=amount, duration=duration
        )
        assert 'buy' in command, command
        self._send_tpp_bot_whisper(command)

    def place_sell_order(self, team: str, price: int=9, amount: int=1, duration: int=1):
        assert isinstance(team, str), type(team)
        assert isinstance(price, int), type(price)
        assert isinstance(amount, int), type(amount)
        assert isinstance(duration, int), type(duration)

        command = 'order sell {team} t{price} {amount} {duration}m'.format(
            team=team, price=price, amount=amount, duration=duration
        )
        assert 'sell' in command, command
        self._send_tpp_bot_whisper(command)

    def get_balance(self):
        command = 'balance'
        self._send_tpp_bot_whisper(command)

    def _send_tpp_bot_whisper(self, command):
        _logger.info('Command: %s', command)
        self._client.connection.privmsg('#jtv', '.w tpp {}'.format(command))


class BetBot(object):
    # \/ Please adjust these:
    MIN_BALANCE = 80  # minimum number of tokens to do anything
    TIER_BALANCE_THRESHOLD = (85, 90, 100, 120, 130, 140)
    TIER_BUY_PRICES = (
        (1,),
        (1, 1, 1, 1, 1, 1, 2, 2, 2, 3),
        (1, 1, 2, 2, 2, 2, 3, 3, 3, 4),
        (1, 2, 2, 2, 2, 2, 3, 4, 5, 6),
        (1, 2, 2, 3, 3, 3, 3, 4, 5, 6),
        (2, 2, 3, 4, 4, 5, 5, 5, 5, 6),
    )
    TIER_SELL_PRICES = tuple(
        tuple(10 - price for price in prices) for prices in TIER_BUY_PRICES
    )
    TIER_BET_CHANCES = (0.4, 0.45, 0.5, 0.6, 0.65, 0.65)
    # /\
    assert len(TIER_BALANCE_THRESHOLD) == len(TIER_BUY_PRICES) == \
        len(TIER_SELL_PRICES) == len(TIER_BET_CHANCES)
    assert TIER_BUY_PRICES[0][0] + TIER_SELL_PRICES[0][0] == 10

    def __init__(self, tpp_bot: TPPBotFacade):
        self._battle_state = BattleState.waiting
        self._tpp_bot = tpp_bot
        self._bet_placed = False
        self._token_balance = 0
        self._cool_off_timestamp = 0

    def set_token_balance(self, tokens: int):
        assert isinstance(tokens, int), type(tokens)
        _logger.info('Update token balance to %s', tokens)
        self._token_balance = tokens

    def start_betting(self):
        _logger.info('Start betting')

        if self._battle_state not in (BattleState.waiting, BattleState.finished):
            self.reset()
        else:
            self.reset(soft=True)

        self._battle_state = BattleState.betting

        current_datetime = datetime.datetime.utcnow()
        timestamp_now = time.time()
        is_dead_hours = 6 < current_datetime.hour < 13

        chance = 0
        current_tier = 0

        for tier_index, tier_balance in enumerate(self.TIER_BALANCE_THRESHOLD):
            chance = self.TIER_BET_CHANCES[tier_index]
            current_tier = tier_index

            if self._token_balance < tier_balance:
                break

        if is_dead_hours:
            chance -= 0.1
            current_tier -= 1
            if current_tier < 0:
                current_tier = 0

        if self._token_balance > self.MIN_BALANCE and \
                (current_datetime.minute <= 2 or 15 <= current_datetime.minute <= 59) and \
                        random.random() < chance and \
                                timestamp_now - self._cool_off_timestamp > 60:
            self._cool_off_timestamp = timestamp_now
            self._place_bet(current_tier)
        else:
            _logger.info('Not betting')

    def start_battle(self):
        _logger.info('Start battle')

        if self._battle_state != BattleState.betting:
            self.reset()
            return

        self._battle_state = BattleState.battle

    def stop_battle(self):
        _logger.info('Stop battle')

        if self._battle_state == BattleState.finished:
            return

        elif self._battle_state != BattleState.battle:
            self.reset()
            return

        self._battle_state = BattleState.finished

        if self._bet_placed:
            self._tpp_bot.get_balance()

    def reset(self, soft=False):
        if self._battle_state == BattleState.waiting:
            return

        if not soft:
            _logger.warning('Reset state. Current=%s', self._battle_state)
        else:
            _logger.info('Reset state')

        self._bet_placed = False
        self._battle_state = BattleState.waiting

    def _place_bet(self, tier_index):
        _logger.info('Placing bet... Tier %s', tier_index)

        assert not self._bet_placed

        self._bet_placed = True

        team = 'blue' if random.randint(0, 1) else 'red'
        duration = random.randint(2, 3)

        if random.random() <= 0.5:
            price = random.choice(self.TIER_BUY_PRICES[tier_index])
            self._tpp_bot.place_buy_order(team, price=price, duration=duration)
        else:
            price = random.choice(self.TIER_SELL_PRICES[tier_index])
            self._tpp_bot.place_sell_order(team, price=price, duration=duration)


class Client(irc.client.SimpleIRCClient):
    def __init__(self):
        super().__init__()

        irc.client.ServerConnection.buffer_class.errors = 'replace'
        self.connection.set_rate_limit(IRC_RATE_LIMIT)
        self._reconnect_interval = RECONNECT_MIN_INTERVAL
        self._running = True
        self._tpp_bot_facade = TPPBotFacade(self)
        self._bet_bot = BetBot(self._tpp_bot_facade)

        self.reactor.execute_every(300, self._keep_alive)

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
        connection.join('#tpp')

        self._tpp_bot_facade.get_balance()

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

        balance_match = re.match(r'you have P(\d+) pokeyen( \(P\d+ reserved\))? T(\d+) tokens?( \(T\d+ reserved\))?', text)

        if balance_match:
            self._bet_bot.set_token_balance(int(balance_match.group(3)))

    def _process_message(self, event):
        username = irc.strings.lower(event.source.nick)

        if not event.arguments:
            return

        if username != 'tpp':
            return

        text = event.arguments[0]

        _logger.info('tpp: %s', text)

        if text.startswith('A new match is about to begin!'):
            self._bet_bot.start_betting()
        elif re.match(r'The battle between .+ has just begun!', text):
            self._bet_bot.start_battle()
        elif re.match(r'Team .+ won the match!', text):
            self._bet_bot.stop_battle()
        elif text == 'The match was automatically cancelled due to an unrecoverable error or crash.':
            self._bet_bot.reset()


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

    client = Client()
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
