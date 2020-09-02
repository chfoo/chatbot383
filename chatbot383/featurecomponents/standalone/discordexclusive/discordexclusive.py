import argparse
import asyncio
import enum
import json
import logging
import os
import random
import re
import signal
import sqlite3
import subprocess
import unicodedata
from typing import Optional

import discord

from chatbot383.roar import gen_roar

_logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    pass


class VoiceState(enum.Enum):
    idle = 'idle'
    playing_cry = 'playing_cry'
    playing_radio = 'playing_radio'


class DiscordExclusiveBot:
    def __init__(self, config):
        self._config = config
        self._client = discord.Client()
        self._db_con = sqlite3.connect(':memory:')

        self._voice_client = None  # type: Optional[discord.VoiceClient]
        self._player = None  # type: Optional[discord.StreamPlayer]
        self._voice_disconnect_task = None
        self._voice_state = VoiceState.idle
        self._current_voice_channel = None  # type: Optional[str]
        self._background_play_task = None

        self._build_pokedex()

    def run(self):
        loop = asyncio.get_event_loop()

        self._voice_disconnect_task = loop.create_task(self._clean_up_voice())
        loop.run_until_complete(self._run_loop())

    async def _run_loop(self):
        while True:
            try:
                await self._session()
            except discord.DiscordException:
                _logger.exception('Discord error')
                await asyncio.sleep(random.randint(60, 300))

    async def _session(self):
        _logger.info('Logging in...')

        try:
            await self._client.login(self._config['token'])
        except discord.LoginFailure as error:
            raise ValueError('Bad token') from error

        # connect() designed as an infinite loop..
        connect_task = asyncio.get_event_loop().create_task(self._client.connect())
        await self._client.wait_until_ready()

        _logger.info('Logged in')

        text_channel = self._client.get_channel(int(self._config['text_channel_id']))
        emojis = tuple(self._client.emojis)

        _logger.info('Listening for messages on %s', text_channel.id)

        while True:
            message_task = asyncio.get_event_loop().create_task(self._client.wait_for('message'))
            done, pending = await asyncio.wait([connect_task, message_task], return_when=asyncio.FIRST_COMPLETED)

            for done_task in done:
                if done_task == message_task:
                    message = await message_task

                    if message.channel != text_channel:
                        continue

                    commands = [
                        self._cry_command,
                        self._move_voice_command,
                        self._radio_command,
                        self._puppy_kick_reaction,
                    ]

                    for command in commands:
                        result = await command(message)

                        if result:
                            break
                else:
                    await done_task

    async def _cry_command(self, message: discord.Message) -> bool:
        match = re.match(r'(?i)!cry(?:\s|$)(.*)', message.content)

        if not match:
            return False

        if self._voice_state == VoiceState.playing_cry:
            return True
        elif self._voice_state == VoiceState.playing_radio:
            self._stop_player()

        await self._join_voice_channel()
        await self._play_cry(match.group(1))

        return True

    async def _play_cry(self, names:str):
        names = names.split()
        sound_ids = []

        self._voice_state = VoiceState.playing_cry

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
                await self._play_and_wait(
                    filename,
                    # before_options='-re',
                    options='-filter:a "volume=-10dB"'
                )

        self._voice_state = VoiceState.idle

    async def _radio_command(self, message: discord.Message) -> bool:
        match = re.match(r'(?i)!radio(?:\s|$)(.*)', message.content)

        if not match:
            return False

        subcommand = match.group(1).lower()

        if self._voice_state == VoiceState.playing_cry:
            await self._stop_player()
        elif self._voice_state == VoiceState.playing_radio:
            if subcommand in ('stop', 'off', 'cancel', 'poweroff'):
                self._stop_player()
                self._voice_state = VoiceState.idle
                await self._client.send_message(
                    message.channel,
                    "{} {} switched radio off 📻🔇".format(
                        gen_roar(),
                        message.author.display_name,
                    ))

            return True

        self._voice_state = VoiceState.playing_radio

        await self._join_voice_channel()

        _logger.info('Playing radio')

        await self._client.send_message(
            message.channel,
            "{} {} switched radio on 📻🎶".format(
                gen_roar(),
                message.author.display_name,
            ))

        options_before = '-re '
        options = '-filter:a "volume=-6dB"'

        if subcommand in ('chef', 'cheg'):
            url = os.path.abspath(
                os.path.join(os.path.dirname(__file__),
                             'Tale_of_the_Spirit_of_Speed_loop.opus')
            )
            options_before += ' -stream_loop -1 '
        else:
            url = await self._get_tpp_stream_url()

            if not url.startswith('http'):
                _logger.error('Url did not start with http: %s', url)
                self._voice_state = VoiceState.idle
                return True

        async def background_play():
            _logger.info('Radio url %s', url)
            await self._play_and_wait(
                url,
                before_options=options_before,
                options=options
            )

            self._voice_state = VoiceState.idle
            self._background_play_task = None
            _logger.info('Radio stopped')

        assert self._background_play_task is None

        self._background_play_task = asyncio.get_event_loop()\
            .create_task(background_play())

        return True

    async def _get_tpp_stream_url(self) -> str:
        proc = await asyncio.create_subprocess_exec(
            'youtube-dl',
            'http://twitch.tv/twitchplayspokemon',
            '--get-url',
            '--format', 'audio_only',
            '--quiet',
            stdout=subprocess.PIPE)

        out_data, in_data = await proc.communicate()

        url = out_data.decode('utf8', 'replace').strip()
        return url

    async def _move_voice_command(self, message: discord.Message):
        match = re.match(r'(?i)!movevoice(?:\s|$)(.*)', message.content)

        if not match:
            return False

        channel_id = match.group(1).strip()

        if not channel_id:
            await self._client.send_message(
                message.channel,
                '\n'.join(
                    'Channel ID {id_str} - <#{id_str}>'.format(id_str=id_str)
                    for id_str in self._config['voice_channel_whitelist']
                )
            )
            return True

        elif channel_id not in self._config['voice_channel_whitelist']:
            await self._client.send_message(
                message.channel,
                "{} Unrecognized voice channel ID".format(gen_roar())
            )
            return True

        self._current_voice_channel = voice_channel = \
            self._client.get_channel(channel_id)

        if self._voice_client:
            _logger.info('Moving voice to %s', voice_channel)
            await self._voice_client.move_to(voice_channel)

        return True

    async def _join_voice_channel(self):
        if self._current_voice_channel is None:
            voice_channel_id = int(self._config['voice_channel_id'])

            self._current_voice_channel = \
                self._client.get_channel(voice_channel_id)

        voice_channel = self._current_voice_channel

        if not self._voice_client:
            _logger.info('Joining voice channel %s', voice_channel.id)
            self._voice_client = await voice_channel.connect()

    async def _clean_up_voice(self):
        while True:
            _logger.debug('Clean up voice schedule, state %s', self._voice_state)

            if self._voice_state == VoiceState.idle and self._voice_client:
                _logger.info('Cleaning up voice')

                await self._voice_client.disconnect()
                self._voice_client = None

            await asyncio.sleep(120)

    async def _play_and_wait(self, *args, **kwargs):
        try:
            self._player = discord.FFmpegPCMAudio(*args, **kwargs)
        except discord.ClientException:
            _logger.error('Player error!')
            return

        self._voice_client.play(self._player)
        while self._voice_client and self._voice_client.is_playing():
            await asyncio.sleep(0.2)

    def _stop_player(self):
        if self._voice_client:
            _logger.debug('Stopping player')
            self._voice_client.stop()
            self._voice_client = None

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

        if not slug:
            raise NotFoundError()

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

    async def _puppy_kick_reaction(self, message: discord.Message) -> bool:
        if message.author.id == self._config.get('puppy_user_id') \
                and message.channel.id == self._config.get('puppy_channel_id') \
                and re.search(r'\bpupp(y|ies)\b', message.content, re.IGNORECASE):

            emojis = self._client.emojis
            emoji_id = int(self._config.get('puppy_emoji_id'))

            for emoji in emojis:
                if emoji.id == emoji_id:
                    await message.add_reaction(emoji)
                    break
            else:
                _logger.error('Puppy emoji missing')

            return True
        else:
            return False

    @classmethod
    def slugify(cls, text, no_dash=False):
        text = text.lower() \
            .replace('♀', 'f') \
            .replace('♂', 'm') \
            .replace(' ', '-')

        if no_dash:
            text = text.replace('-', '')

        text = cls.remove_accents(text)
        text = re.sub(r'[^a-zA-Z0-9-]', '', text)
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
