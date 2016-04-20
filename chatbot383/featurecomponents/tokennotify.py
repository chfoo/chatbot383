import logging
import os

import time

from chatbot383.bot import Limiter
from chatbot383.roar import gen_roar

_logger = logging.getLogger(__name__)


class TokenNotifier(object):
    def __init__(self, token_analysis_filename, channels, update_interval=60):
        self._token_analysis_filename = token_analysis_filename
        self._channels = channels
        self._update_interval = update_interval
        self._last_button_labels = frozenset()
        self._last_timestamp = None
        self._limiter = Limiter(30)

    def notify(self, bot):
        doc = self._read_file()

        if not doc:
            return

        _logger.info('Check for tokens')

        next_interval = self._get_next_update_interval()

        token_button_labels = set()
        no_token_button_labels = set()

        for button_label in sorted(doc['buttons'].keys()):
            button_doc = doc['buttons'][button_label]

            if button_doc['token_detected']:
                token_button_labels.add(button_label)
            else:
                no_token_button_labels.add(button_label)

        if self._last_button_labels == token_button_labels:
            return next_interval

        self._last_button_labels = frozenset(token_button_labels)

        if not token_button_labels or not no_token_button_labels:
            # No tokens or all buttons have tokens (likely false positive)
            return next_interval

        if self._limiter.is_ok(None):
            self._limiter.update(None)
            self._send_to_channels(bot, token_button_labels)

        return next_interval

    def _read_file(self):
        if not self._token_analysis_filename or \
                not os.path.isfile(self._token_analysis_filename) or \
                not self._channels:
            self._last_timestamp = None
            return

        time_now = time.time()
        file_timestamp = os.path.getmtime(self._token_analysis_filename)

        if time_now - file_timestamp > 120 or \
                self._last_timestamp == file_timestamp:
            return

        if not self._last_timestamp:
            _logger.info('Found token analysis file')

        self._last_timestamp = file_timestamp

        with open(self._token_analysis_filename) as file:
            try:
                doc = json.load(file)
            except ValueError:
                _logger.exception('Error reading file')
                return
            else:
                return doc

    def _get_next_update_interval(self):
        if not self._last_timestamp:
            return

        time_now = time.time()
        interval = self._update_interval - (time_now - self._last_timestamp)
        interval = min(300, interval)
        interval = max(5, interval)

        return interval

    def _send_to_channels(self, bot, token_button_labels):
        text = '[Token] {roar} Detected tokens on: {buttons}' \
            .format(
                roar=gen_roar(),
                buttons=', '.join(sorted(token_button_labels))
            )

        for channel in self._channels:
            _logger.info('Token notify to %s', channel)
            bot.send_text(channel, text)
