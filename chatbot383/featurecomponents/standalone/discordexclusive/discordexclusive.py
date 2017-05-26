import argparse
import asyncio
import json
import os
import random
import re
import signal
import unicodedata
import logging

import discord
import sqlite3

_logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    pass


class DiscordExclusiveBot:
    def __init__(self, config):
        self._config = config
        self._client = discord.Client()
        self._db_con = sqlite3.connect(':memory:')
        self._voice_client = None
        self._build_pokedex()
        self._voice_disconnect_timer_handle = None
        self._voice_busy = False

    def run(self):
        asyncio.get_event_loop().run_until_complete(self._run_loop())

    @asyncio.coroutine
    def _run_loop(self):
        while True:
            try:
                yield from self._session()
            except discord.DiscordException:
                _logger.exception('Discord error')
                yield from asyncio.sleep(random.randint(60, 300))

    @asyncio.coroutine
    def _session(self):
        _logger.info('Logging in...')

        try:
            yield from self._client.login(self._config['token'])
        except discord.LoginFailure as error:
            raise ValueError('Bad token') from error

        asyncio.get_event_loop().create_task(self._client.connect())
        yield from self._client.wait_until_ready()

        _logger.info('Logged in')

        text_channel = self._client.get_channel(self._config['text_channel_id'])
        emojis = tuple(self._client.get_all_emojis())

        _logger.info('Listening for messages on %s', text_channel.id)

        while True:
            message = yield from self._client.wait_for_message(channel=text_channel)

            match = re.match(r'(?i)!cry(?:\s|$)(.*)', message.content)

            if match:
                if self._voice_busy:
                    continue

                yield from self._join_voice_channel()
                # yield from self._client.add_reaction(message, random.choice(emojis))
                yield from self._cry_command(match.group(1))
                # yield from self._client.add_reaction(message, random.choice(emojis))

    @asyncio.coroutine
    def _cry_command(self, names:str):
        names = names.split()
        sound_ids = []

        self._voice_busy = True

        for name in names:
            try:
                sound_id = self._lookup_sound_id(name)
            except NotFoundError:
                sound_ids.append(self._lookup_sound_id(str(random.randint(1, 802))))
                continue
            else:
                sound_ids.append(sound_id)

        if not sound_ids:
            sound_ids.append(self._lookup_sound_id(str(random.randint(1, 802))))

        for sound_ids in sound_ids[:5]:
            filename = self._get_sound_path(sound_ids)

            if os.path.isfile(filename):
                player = self._voice_client.create_ffmpeg_player(filename,
                    # before_options='-re'
                )
                player.start()
                while not player.is_done():
                    yield from asyncio.sleep(0.2)

        self._voice_busy = False

    @asyncio.coroutine
    def _join_voice_channel(self):
        if self._voice_disconnect_timer_handle:
            self._voice_disconnect_timer_handle.cancel()
            self._voice_disconnect_timer_handle = None

        voice_channel = self._client.get_channel(self._config['voice_channel_id'])

        if not self._voice_client or self._voice_client.channel != voice_channel:
            if self._voice_client:
                yield from self._voice_client.disconnect()

            _logger.info('Joining voice channel %s', voice_channel.id)
            self._voice_client = yield from self._client.join_voice_channel(voice_channel)

        loop = asyncio.get_event_loop()

        def cleanup_voice():
            _logger.debug('Cleaning up voice')
            self._voice_disconnect_timer_handle = None
            loop.create_task(self._voice_client.disconnect())
            self._voice_client = None

        self._voice_disconnect_timer_handle = loop.call_later(20, cleanup_voice)

    def _build_pokedex(self):
        _logger.info('Building sound pokedex...')

        self._db_con.execute('''CREATE TABLE pokedex (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            species_id INTEGER NOT NULL,
            form TEXT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            path TEXT NOT NULL
            )
        ''')

        count = 0

        for filename in os.listdir(self._config['sound_file_directory']):
            if not filename.endswith('.opus'):
                continue

            path = os.path.join(self._config['sound_file_directory'], filename)

            match = re.match('(\d+)(\w*) - (.+)\.opus$', filename)

            if not match:
                continue

            species_id = int(match.group(1))
            species_form = match.group(2).lower() or None
            species_name = match.group(3)
            slug = self.slugify(species_name, no_dash=True)

            self._db_con.execute('''INSERT INTO pokedex
                (species_id, form, name, slug, path)
                 VALUES (?, ?, ?, ?, ?)
            ''', (species_id, species_form, species_name, slug, path))
            count += 1

        self._db_con.execute('''CREATE INDEX id_index ON pokedex (species_id)''')
        self._db_con.execute('''CREATE INDEX slug_index ON pokedex (slug)''')

        _logger.info('Built sound pokedex with %s files', count)

        if not count:
            raise Exception("No files found")

    def _lookup_sound_id(self, name: str) -> int:
        match = re.match(r'(\d+)(\w*)', name)

        if match:
            species_id = int(match.group(1))
            form = match.group(2).lower() or None

            if not form:
                row = self._db_con.execute(
                    '''
                    SELECT id
                    FROM pokedex
                    WHERE species_id = ? AND form IS NULL
                    ''',
                    (species_id,)
                ).fetchone()
            else:
                row = self._db_con.execute(
                    '''
                    SELECT id
                    FROM pokedex
                    WHERE species_id = ? AND form = ?
                    ''',
                    (species_id, form)
                ).fetchone()

            if row:
                return row[0]

        slug = self.slugify(name, no_dash=True)

        row = self._db_con.execute(
            '''
            SELECT id
            FROM pokedex
            WHERE slug LIKE ? || '%'
            ''',
            (slug,)
        ).fetchone()

        if not row:
            raise NotFoundError()

        return row[0]

    def _get_sound_path(self, sound_id: int) -> str:
        row = self._db_con.execute('''
            SELECT path FROM pokedex
            WHERE id = ?
        ''', (sound_id, )).fetchone()

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

    def stop(self):
        _logger.info('Stopping')
        loop = asyncio.get_event_loop()

        if self._voice_client:
            loop.create_task(self._voice_client.disconnect())

        loop.create_task(self._client.close())


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('config_file', type=argparse.FileType('r'))

    args = arg_parser.parse_args()

    doc = json.load(args.config_file)

    bot = DiscordExclusiveBot(doc)

    def cleanup(dummy1, dummy2):
        bot.stop()
        asyncio.get_event_loop().call_later(1, asyncio.get_event_loop().stop)
        asyncio.get_event_loop().call_later(2, asyncio.get_event_loop().close)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    bot.run()

if __name__ == '__main__':
    main()
