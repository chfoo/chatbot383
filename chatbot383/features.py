import collections
import random
import re

import sqlite3

import time

from chatbot383.roar import gen_roar


class MailbagFullError(ValueError):
    pass


class Database(object):
    def __init__(self, db_path):
        self._path = db_path
        self._con = sqlite3.connect(db_path)

        self._init_db()

    def _init_db(self):
        with self._con:
            self._con.execute('''CREATE TABLE IF NOT EXISTS mail
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            username TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL
            )
            ''')
            self._con.execute('''CREATE INDEX IF NOT EXISTS mail_status_index
            ON mail (status)
            ''')

    def get_mail(self):
        with self._con:
            row = self._con.execute('''SELECT id, username, text FROM
            mail WHERE status = ?''', ('unread',)).fetchone()

            if row:
                mail_info = {
                    'username': row[1],
                    'text': row[2]
                }
                self._con.execute('''UPDATE mail SET status = ?
                WHERE id = ?''', ('read', row[0]))
                return mail_info

    def put_mail(self, username, text):
        with self._con:
            row = self._con.execute('''SELECT count(1) FROM mail
            WHERE status = 'unread' ''').fetchone()

            if row[0] >= 5:
                raise MailbagFullError()

            self._con.execute('''INSERT INTO mail
            (timestamp, username, text, status) VALUES (?, ?, ?, 'unread')
            ''', (int(time.time()), username, text))


class Features(object):
    def __init__(self, bot, help_text, database):
        self._bot = bot
        self._help_text = help_text
        self._database = database
        self._recent_messages = collections.defaultdict(lambda: collections.deque(maxlen=10))

        bot.register_message_handler('pubmsg', self._collect_recent_message)
        bot.register_message_handler('action', self._collect_recent_message)
        bot.register_command(r'!(groudonger)?help($|\s.*)', self._help_command)
        bot.register_command(r's/(.+)/(.+)/([gi]*)', self._regex_command)
        bot.register_command(r'!groudon(ger)?($|\s.*)', self._roar_command)
        bot.register_command(r'!klappa($|\s.*)', self._klappa_command)
        bot.register_command(r'!(mail|post)($|\s.{,100})$', self._mail_command)
        bot.register_command(r'!riot($|\s.*)', self._riot_command)
        bot.register_command(r'!rip (.{,50})$', self._rip_command)

    def _collect_recent_message(self, session):
        if session.message['event_type'] in ('pubmsg', 'action'):
            channel = session.message['channel']
            self._recent_messages[channel].append(session.message)

    def _help_command(self, session):
        session.reply('{} {}'.format(gen_roar(), self._help_text))

    def _roar_command(self, session):
        session.say('{} {} {}'.format(gen_roar(), gen_roar(), gen_roar().upper()))

    def _regex_command(self, session):
        search_pattern = session.match.group(1)
        replacement = session.match.group(2)
        options = session.match.group(3)
        flags = 0
        count = 1

        if 'i' in options:
            flags |= re.IGNORECASE

        if 'g' in options:
            count = 0

        try:
            pattern = re.compile(search_pattern, flags)
        except re.error as error:
            session.reply('{} {}!'.format(gen_roar(), error.args[0].title()))
            return

        for history_message in reversed(self._recent_messages[session.message['channel']]):
            text = history_message['text']

            if text.startswith('s/'):
                continue

            if pattern.search(text):
                try:
                    new_text = pattern.sub(replacement, text, count=count)
                except re.error as error:
                    session.reply('{} {}!'.format(gen_roar(), error.args[0].title()))
                    return

                if len(new_text) > 400:
                    session.reply('{} Message length exceeds my capabilities!'
                                  .format(gen_roar()))
                    return

                if random.random() < 0.1:
                    new_text = gen_roar()

                session.say(
                    '{user} wishes to correct {target_user}: {text}'.format(
                        user=session.message['nick'],
                        target_user=history_message['nick'],
                        text=new_text
                    )
                )
                return

        session.reply('{} Your request does not apply to any recent messages!'
                      .format(gen_roar()))

    def _riot_command(self, session):
        session.say('{} Riot, I say! Riot, you may! {}'
                    .format(gen_roar(), gen_roar().upper()))

    def _rip_command(self, session):
        session.say('{} Rest in peace, {}. Press F to pay your respects.'
                    .format(gen_roar(), session.match.group(1)))

    def _klappa_command(self, session):
        session.say('{}'.format(gen_roar()))

    def _mail_command(self, session):
        mail_text = session.match.group(2).strip()

        if mail_text:
            try:
                self._database.put_mail(session.message['username'], mail_text)
            except MailbagFullError:
                session.reply(
                    '{} Incredulous! My mailbag is full! Read one instead!'
                    .format(gen_roar()))
            else:
                session.reply(
                    'Tremendous! I will deliver this mail to the next '
                    'recipient without fail! {}'.format(gen_roar()))
        else:
            mail_info = self._database.get_mail()

            if not mail_info:
                session.reply(
                    '{} Outlandish! There is no mail! You should send some!'
                    .format(gen_roar())
                )
            else:
                session.reply(
                    '{} I am delivering mail! Here it is from {}: {}'
                    .format(gen_roar(), mail_info['username'],
                            mail_info['text'])
                )
