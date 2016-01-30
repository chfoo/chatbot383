import collections
import copy
import random
import re

import sqlite3

import time

import arrow

from chatbot383.bot import Limiter
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
            self._con.execute('''PRAGMA journal_mode=WAL;''')
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
            row = self._con.execute('''SELECT id, username, text, timestamp FROM
            mail WHERE status = ? LIMIT 1''', ('unread',)).fetchone()

            if row:
                mail_info = {
                    'username': row[1],
                    'text': row[2],
                    'timestamp': row[3],
                }
                self._con.execute('''UPDATE mail SET status = ?
                WHERE id = ?''', ('read', row[0]))
                return mail_info

    def get_old_mail(self):
        with self._con:
            row = self._con.execute('''SELECT max(id) FROM mail''').fetchone()

            max_id = row[0]

            row = self._con.execute(
                '''SELECT username, text, timestamp FROM
                mail WHERE status = ? AND id > ?''',
                ('read', random.randint(0, max_id))
            ).fetchone()

            if row:
                mail_info = {
                    'username': row[0],
                    'text': row[1],
                    'timestamp': row[2],
                }
                return mail_info

    def put_mail(self, username, text):
        with self._con:
            row = self._con.execute('''SELECT count(1) FROM mail
            WHERE status = 'unread' LIMIT 1''').fetchone()

            if row[0] >= 50:
                raise MailbagFullError()

            self._con.execute('''INSERT INTO mail
            (timestamp, username, text, status) VALUES (?, ?, ?, 'unread')
            ''', (int(time.time()), username, text))

    def get_status_count(self, status):
        with self._con:
            row = self._con.execute('''SELECT count(1) FROM mail
            WHERE status = ? LIMIT 1''', (status,)).fetchone()

            return row[0]


class Features(object):
    DONGER_SONG_TEMPLATE = (
        'I like to raise my {donger} I do it all the time ヽ༼ຈل͜ຈ༽ﾉ '
        'and every time its lowered┌༼ຈل͜ຈ༽┐ '
        'I cry and start to whine ┌༼@ل͜@༽┐'
        'But never need to worry ༼ ºل͟º༽ '
        'my {donger}\'s staying strong ヽ༼ຈل͜ຈ༽ﾉ'
        'A {donger} saved is a {donger} earned so sing the {donger} song!'
    )
    TOO_LONG_TEXT_TEMPLATE = '{} Message length exceeds my capabilities!'

    def __init__(self, bot, help_text, database):
        self._bot = bot
        self._help_text = help_text
        self._database = database
        self._recent_messages_for_regex = collections.defaultdict(lambda: collections.deque(maxlen=100))
        self._spam_limiter = Limiter(min_interval=10)

        bot.register_message_handler('pubmsg', self._collect_recent_message)
        bot.register_message_handler('action', self._collect_recent_message)
        bot.register_command(r'(?i)!double(team)?($|\s.*)', self._double_command)
        bot.register_command(r'(?i)!(groudonger)?help($|\s.*)', self._help_command)
        bot.register_command(r's/(.+/.*)', self._regex_command)
        bot.register_command(r'(?i)!groudon(ger)?($|\s.*)', self._roar_command)
        bot.register_command(r'(?i)!klappa($|\s.*)', self._klappa_command)
        bot.register_command(r'(?i)!(mail|post)($|\s.*)$', self._mail_command)
        bot.register_command(r'(?i)!(mail|post)status($|\s.*)', self._mail_status_command)
        bot.register_command(r'(?i)!pick\s+(.*)', self._pick_command)
        bot.register_command(r'(?i)!praise($|\s.{,100})$', self._praise_command)
        bot.register_command(r'(?i)!shuffle\s+(.*)', self._shuffle_command)
        bot.register_command(r'(?i)!song($|\s.{,50})$', self._song_command)
        bot.register_command(r'(?i)!sort\s+(.*)', self._sort_command)
        bot.register_command(r'(?i)!rand(?:om)?case\s+(.*)', self._rand_case_command)
        bot.register_command(r'(?i)!riot($|\s.{,100})$', self._riot_command)
        bot.register_command(r'(?i)!rip($|\s.{,100})$', self._rip_command)
        bot.register_command(r'(?i)!(xd|minglee|chfoo)($|\s.*)', self._xd_command)
        bot.register_command(r'.*\b[xX][dD] +MingLee\b.*', self._xd_rand_command)

    @classmethod
    def is_too_long(cls, text):
        return len(text.encode('utf-8', 'replace')) > 400

    @classmethod
    def _try_say_or_reply_too_long(cls, formatted_text, session):
        if cls.is_too_long(formatted_text):
            session.reply(cls.TOO_LONG_TEXT_TEMPLATE.format(gen_roar()))
            return False
        else:
            session.say(formatted_text)
            return True

    def _collect_recent_message(self, session):
        if session.message['event_type'] in ('pubmsg', 'action'):
            channel = session.message['channel']
            username = session.message['username']
            our_username = session.client.get_nickname(lower=True)

            if username != our_username:
                self._recent_messages_for_regex[channel].append(session.message)

    def _help_command(self, session):
        session.reply('{} {}'.format(gen_roar(), self._help_text))

    def _roar_command(self, session):
        session.say('{} {} {}'.format(gen_roar(), gen_roar(), gen_roar().upper()))

    def _regex_command(self, session):
        # Special split http://stackoverflow.com/a/21107911/1524507
        parts = re.split(r'(?<!\\)/', session.match.group(1))

        if not (2 <= len(parts) <= 3):
            return

        search_pattern = parts[0]
        replacement = parts[1]
        options = parts[2] if len(parts) == 3 else ''
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

        for history_message in reversed(self._recent_messages_for_regex[session.message['channel']]):
            text = history_message['text']
            channel = session.message['channel']

            if text.startswith('s/'):
                continue

            if pattern.search(text):
                try:
                    new_text = pattern.sub(replacement, text, count=count)
                except re.error as error:
                    session.reply('{} {}!'.format(gen_roar(), error.args[0].title()))
                    return

                if random.random() < 0.1:
                    new_text = gen_roar()
                    fake_out = True
                else:
                    fake_out = False

                formatted_text = '{user} wishes to {stacked}correct ' \
                    '{target_user}: {text}'.format(
                        user=session.message['nick'],
                        target_user=history_message['nick'],
                        text=new_text,
                        stacked='re' if history_message.get('stacked') else '',
                )

                ok = self._try_say_or_reply_too_long(formatted_text, session)
                if not ok:
                    return

                if not fake_out:
                    stacked_message = copy.copy(history_message)
                    stacked_message['text'] = new_text
                    stacked_message['stacked'] = True
                    self._recent_messages_for_regex[channel].append(stacked_message)

                return

        session.reply('{} Your request does not apply to any recent messages!'
                      .format(gen_roar()))

    def _double_command(self, session):
        text = session.match.group(2).strip()

        if not text:
            text = 'ヽ༼ຈل͜ຈ༽ﾉ DOUBLE TEAM ヽ༼ຈل͜ຈ༽ﾉ'

        double_text = ''.join(char * 2 for char in text)
        formatted_text = '{} Doubled! {}'.format(gen_roar(), double_text)

        self._try_say_or_reply_too_long(formatted_text, session)

    def _pick_command(self, session):
        text = session.match.group(1).strip()

        if not text:
            return

        result = random.choice(text.split(',')).strip()
        formatted_text = '{} Picked! {}'.format(gen_roar(), result)

        self._try_say_or_reply_too_long(formatted_text, session)

    def _praise_command(self, session):
        text = session.match.group(1).strip()

        if text:
            formatted_text = '{} Praise {}!'.format(gen_roar(), text)
        else:
            formatted_text = '{} Praise it! Raise it!'.format(gen_roar())

        self._try_say_or_reply_too_long(formatted_text, session)

    def _shuffle_command(self, session):
        text = session.match.group(1).strip()

        if not text:
            return

        shuffle_list = list(text)
        random.shuffle(shuffle_list)
        shuffle_text = ''.join(shuffle_list).strip()

        formatted_text = '{} Shuffled! {}'.format(gen_roar(), shuffle_text)

        self._try_say_or_reply_too_long(formatted_text, session)

    def _song_command(self, session):
        limiter_key = ('song', session.message['channel'])
        if not self._spam_limiter.is_ok(limiter_key):
            return

        text = session.match.group(1).strip()

        if not text:
            text = 'Groudonger'

        formatted_text = self.DONGER_SONG_TEMPLATE.format(donger=text)

        self._try_say_or_reply_too_long(formatted_text, session)

        self._spam_limiter.update(limiter_key)

    def _sort_command(self, session):
        text = session.match.group(1).strip()

        if not text:
            return

        sorted_text = ''.join(sorted(text)).strip()
        formatted_text = '{} Sorted! {}'.format(gen_roar(), sorted_text)

        self._try_say_or_reply_too_long(formatted_text, session)

    def _rand_case_command(self, session):
        text = session.match.group(1).strip()

        rand_case_text = ''.join(
            char.swapcase() if random.randint(0, 1) else char for char in text
        )

        formatted_text = '{} Random case! {}'.format(gen_roar(), rand_case_text)

        self._try_say_or_reply_too_long(formatted_text, session)

    def _riot_command(self, session):
        text = session.match.group(1).strip()

        if text:
            formatted_text = '{} {} or riot! {}'\
                .format(gen_roar(), text, gen_roar().upper())
        else:
            formatted_text = \
                '{} {} {}'.format(
                    gen_roar(),
                    random.choice((
                        'Riot, I say! Riot, you may!',
                        'Riot!',
                        '{} riot!'.format(session.message['nick']),
                        'Groudonger riot!',
                    )),
                    gen_roar().upper()
                )

        self._try_say_or_reply_too_long(formatted_text, session)

    def _rip_command(self, session):
        text = session.match.group(1).strip() or session.message['nick']

        formatted_text = \
            '{} {}, {}. Press F to pay your respects.'.format(
                gen_roar(), random.choice(('RIP', 'Rest in peace')), text
            )

        self._try_say_or_reply_too_long(formatted_text, session)

    def _klappa_command(self, session):
        session.say('{}'.format(random.choice(('Kappa //', gen_roar()))))

    def _xd_command(self, session):
        session.say('{} xD MingLee'.format(
            gen_roar().lower().replace('!', '?'))
        )

    def _xd_rand_command(self, session):
        if random.random() < 0.1 or \
                session.message['username'] == 'wow_deku_onehand' and \
                session.message['text'].strip() == 'xD MingLee':
            def rep_func(match):
                return '!' if random.random() < 0.6 else '1'

            session.say('{} xD MingLee'.format(
                re.sub('!', rep_func, gen_roar().lower()))
            )

    def _mail_command(self, session):
        mail_text = session.match.group(2).strip()

        if mail_text:
            if len(mail_text) > 200:
                session.reply('{} Your message is too burdensome! '
                              'Send a concise version instead.'
                              .format(gen_roar()))
                return

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
            if random.random() < 0.3:
                mail_info = self._database.get_old_mail()
            else:
                mail_info = self._database.get_mail()

                if not mail_info and random.random() < 0.3:
                    mail_info = self._database.get_old_mail()

            if not mail_info:
                session.reply(
                    '{} Outlandish! There is no mail! You should send some!'
                    .format(gen_roar())
                )
            else:
                session.reply(
                    '{roar} I am delivering mail! '
                    'Here it is, {date}, from {username}: {msg}'
                    .format(
                        roar=gen_roar(),
                        username=mail_info['username'],
                        date=arrow.get(mail_info['timestamp']).humanize(),
                        msg=mail_info['text'])
                )

    def _mail_status_command(self, session):
        unread_count = self._database.get_status_count('unread')
        read_count = self._database.get_status_count('read')

        session.reply(
            '{roar} {unread} unread, {read} read, {total} total!'.format(
                roar=gen_roar(),
                unread=unread_count,
                read=read_count,
                total=unread_count + read_count
            )
        )
