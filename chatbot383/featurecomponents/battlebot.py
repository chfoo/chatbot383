import enum
import logging
import re
import sqlite3
import collections

from chatbot383.bot import InboundMessageSession, Bot
from chatbot383.roar import gen_roar
from chatbot383.util import weighted_choice

BATTLEBOT_USERNAME = 'wow_battlebot_onehand'
BATTLEBOT_CHANNEL = '#_keredau_1423645868201'
CHALLENGE_PATTERN = re.compile(r'You have been challenged to a Pokemon Battle by ([a-zA-Z0-9_]+)', re.IGNORECASE)
SENDER_PATTERN = re.compile(r'([a-zA-Z0-9_]+) sends out ([^(]+) \(level (\d+)\)', re.IGNORECASE)
SWITCH_PATTERN = re.compile(r'([a-zA-Z0-9_]+) calls back .+ and sent out ([^!]+)!', re.IGNORECASE)
PROMPT_FOR_MOVE_PATTERN = re.compile(r'What will [^ ]+ do\?', re.IGNORECASE)
PROMPT_FOR_SWITCH_PATTERN = re.compile(r'Type !switch', re.IGNORECASE)
MOVE_SELECTION_PATTERN = re.compile(r'What will ([^ ]+) do\? (.+) \(!help', re.IGNORECASE)
WINNER_PATTERN = re.compile(r'(\w+) wins!', re.IGNORECASE)


_logger = logging.getLogger(__name__)


PokemonInfo = collections.namedtuple(
    'PokemonInfo',
    ['id', 'species_id', 'type_ids']
)

MoveInfo = collections.namedtuple(
    'MoveInfo', ['id', 'type_id', 'power', 'accuracy']
)


class NotFound(Exception):
    pass


class BattleState(enum.Enum):
    challenged = 'challenged'
    in_battle = 'in_battle'


class PokemonStats(object):
    def __init__(self, dex_info: PokemonInfo):
        self.dex_info = dex_info
        self.level = None
        self.moves = []


class BattleSession(object):
    def __init__(self, opponent_username: str, type_efficacy_table: dict):
        self._opponent_username = opponent_username
        self._type_efficacy_table = type_efficacy_table
        self._state = BattleState.challenged
        self._current_pokemon = None
        self._opponent_pokemon = None

    @property
    def opponent_username(self):
        return self._opponent_username

    @property
    def state(self):
        return self._state

    @property
    def current_pokemon(self) -> PokemonStats:
        return self._current_pokemon

    @current_pokemon.setter
    def current_pokemon(self, pokemon: PokemonStats):
        self._current_pokemon = pokemon

    @property
    def opponent_pokemon(self) -> PokemonStats:
        return self._opponent_pokemon

    @opponent_pokemon.setter
    def opponent_pokemon(self, pokemon: PokemonStats):
        self._opponent_pokemon = pokemon

    def get_switch(self):
        return 0

    def get_move(self) -> int:
        candidate_moves = []

        for index, move_info in enumerate(self._current_pokemon.moves):
            damage_type_id = move_info.type_id
            total_damage_factor = 1.0

            for target_type_id in self._opponent_pokemon.dex_info.type_ids:
                damage_factor = self._type_efficacy_table[(damage_type_id, target_type_id)] / 100

                total_damage_factor *= damage_factor

            if move_info.type_id in self._current_pokemon.dex_info.type_ids:
                stab = 1.5
            else:
                stab = 1.0

            accuracy = move_info.accuracy / 100 if move_info.accuracy else 1.0

            if not move_info.power:
                score = 10
            else:
                score = move_info.power * total_damage_factor * accuracy * stab

            candidate_moves.append((index, score))

        picked_move = weighted_choice(candidate_moves)

        _logger.info('Move candidates: %s', candidate_moves)

        return picked_move


class BattleBot(object):
    def __init__(self, db_path: str, bot: Bot):
        self._path = db_path
        self._con = sqlite3.connect(db_path)
        self._bot = bot
        self._battle_session = None

    @property
    def session(self) -> BattleSession:
        return self._battle_session

    def message_callback(self, session: InboundMessageSession):
        event_type = session.message['event_type']

        try:
            if event_type == 'whisper':
                self._handle_whisper(session)
            elif event_type == 'pubmsg':
                self._handle_message(session)
        except Exception:
            _logger.exception('Battle Bot Error!')

    def _handle_whisper(self, session: InboundMessageSession):
        if session.message['username'] != BATTLEBOT_USERNAME:
            return

        text = session.message['text']

        self._parse_text(text)

    def _handle_message(self, session: InboundMessageSession):
        if session.message['channel'] != BATTLEBOT_CHANNEL:
            return

        if session.message['username'] != BATTLEBOT_USERNAME:
            return

        text = session.message['text']

        self._parse_text(text)

    def _parse_text(self, text):
        if CHALLENGE_PATTERN.search(text):
            self._start_battle(CHALLENGE_PATTERN.search(text).group(1))

        if self._battle_session:
            if PROMPT_FOR_MOVE_PATTERN.search(text):
                self._parse_current_moves(text)
                self._execute_move()
            elif PROMPT_FOR_SWITCH_PATTERN.search(text):
                self._execute_switch()
            elif WINNER_PATTERN.search(text):
                self._end_battle()
            elif SENDER_PATTERN.search(text):
                self._parse_opponent_pokemon(text)
            elif SWITCH_PATTERN.search(text):
                self._parse_opponent_switch(text)

    def _start_battle(self, opponent_username: str):
        opponent_username = opponent_username.lower()

        _logger.info('Start battle with %s', opponent_username)

        self._battle_session = BattleSession(opponent_username, self._get_type_efficacy_table())

        self._bot.send_text(BATTLEBOT_CHANNEL, gen_roar())
        self._bot.send_whisper(BATTLEBOT_USERNAME, '!accept', allow_command_prefix=True)

    def _end_battle(self):
        _logger.info('End battle')
        self._bot.send_text(BATTLEBOT_CHANNEL, gen_roar())
        self._battle_session = None

    def _execute_move(self):
        move_index = self._battle_session.get_move() + 1
        _logger.info('Do move %s', move_index)
        self._bot.send_whisper(BATTLEBOT_USERNAME, '!move{}'.format(move_index), allow_command_prefix=True)

    def _execute_switch(self):
        switch_index = self._battle_session.get_switch()
        _logger.info('Switch to %s', switch_index)
        self._bot.send_whisper(BATTLEBOT_USERNAME, '!switch{}'.format(switch_index), allow_command_prefix=True)

    def _parse_current_moves(self, text):
        match = MOVE_SELECTION_PATTERN.search(text)
        pokemon_name = match.group(1)
        move_text = match.group(2)

        pokemon = self._new_pokemon(pokemon_name)

        for part in move_text.split(','):
            name = part.split(')', 1)[-1]
            name = name.strip()

            pokemon.moves.append(self._get_move_info(name))

        self._battle_session.current_pokemon = pokemon

        _logger.info('Current moves for %s: %s',
                     pokemon.dex_info.species_id, pokemon.moves)

    def _parse_opponent_pokemon(self, text):
        matches = SENDER_PATTERN.finditer(text)

        for match in matches:
            if match:
                username = match.group(1).lower()
                if username != self._battle_session.opponent_username:
                    continue

                name = match.group(2)
                level = int(match.group(3))

                opponent_pokemon = self._new_pokemon(name)
                self._battle_session.opponent_pokemon = opponent_pokemon
                self._battle_session.opponent_pokemon.level = level

                _logger.info('Opponent pokemon: %s',
                             opponent_pokemon.dex_info.species_id)

    def _parse_opponent_switch(self, text):
        match = SWITCH_PATTERN.search(text)

        if match:
            username = match.group(1).lower()
            if username != self._battle_session.opponent_username:
                return

            name = match.group(2)

            opponent_pokemon = self._new_pokemon(name)
            self._battle_session.opponent_pokemon = opponent_pokemon

            _logger.info('Opponent pokemon: %s',
                         opponent_pokemon.dex_info.species_id)

    def _new_pokemon(self, name) -> PokemonStats:
        pokemon = PokemonStats(self._get_pokemon_info(name))
        return pokemon

    def _get_pokemon_info(self, name) -> PokemonInfo:
        slug = self.slugify(name, no_dash=True)

        row = self._con.execute(
            '''
            SELECT id, species_id
            FROM pokemon
            WHERE replace(identifier, '-', '') LIKE ?
            ''',
            ('{}%'.format(slug),)
        ).fetchone()

        if not row:
            raise NotFound('Pokemon {} not found'.format(name))

        pokemon_id, species_id = row
        pokemon_type_ids = set()

        query = self._con.execute(
            '''
            SELECT type_id FROM pokemon_types WHERE pokemon_id = ?
            ''',
            (pokemon_id,)
        )

        for row in query:
            pokemon_type_ids.add(row[0])

        return PokemonInfo(pokemon_id, species_id, pokemon_type_ids)

    def _get_move_info(self, name) -> MoveInfo:
        slug = self.slugify(name, no_dash=True)

        row = self._con.execute(
            '''SELECT id, type_id, power, accuracy
            FROM moves WHERE replace(identifier, '-', '') = ?
            ''',
            (slug,)
        ).fetchone()

        if row:
            return MoveInfo(row[0], row[1], row[2], row[3])
        else:
            raise NotFound('Move {} not found'.format(name))

    def _get_type_efficacy_table(self) -> dict:
        query = self._con.execute(
            '''SELECT
            damage_type_id, target_type_id, damage_factor
            FROM type_efficacy
            ''',

        )
        table = dict()

        for damage_type_id, target_type_id, damage_factor in query:
            table[(damage_type_id, target_type_id)] = damage_factor

        return table

    @classmethod
    def slugify(cls, text, no_dash=False):
        text = text.lower()\
            .replace('♀', 'f')\
            .replace('♂', 'm')\
            .replace(' ', '-')

        if no_dash:
            text = text.replace('-', '')

        text = re.sub(r'[^a-zA-Z-]', '', text)
        return text
