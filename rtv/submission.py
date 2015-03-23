import curses
import sys
import time

import praw.errors

from .content import SubmissionContent
from .page import BasePage, Controller
from .helpers import clean, open_browser
from .curses_helpers import (BULLET, UARROW, DARROW, Color, LoadScreen,
                             text_input)

__all__ = ['SubmissionController', 'SubmissionPage']

class SubmissionController(Controller):
    """Controller for submission page."""
    character_map = {}

class SubmissionPage(BasePage):

    def __init__(self, stdscr, reddit, url=None, submission=None):

        self.controller = SubmissionController(self)
        self.loader = LoadScreen(stdscr)

        if url is not None:
            content = SubmissionContent.from_url(reddit, url, self.loader)
        elif submission is not None:
            content = SubmissionContent(submission, self.loader)
        else:
            raise ValueError('Must specify url or submission')

        super(SubmissionPage, self).__init__(stdscr, reddit, content,
                                             page_index=-1)

    def loop(self):

        self.active = True
        while self.active:
            self._draw_page()
            cmd = self.stdscr.getch()
            self.controller.trigger(cmd)

    @SubmissionController.register('h', curses.KEY_LEFT)
    def exit_submission(self):
        """
        Return to the subreddit page.
        """
        self.active = False

    @SubmissionController.register(curses.KEY_RIGHT, curses.KEY_ENTER, 'l')
    def toggle_comment(self):
        current_index = self.nav.absolute_index
        self.content.toggle(current_index)
        if self.nav.inverted:
            # Reset the page so that the bottom is at the cursor position.
            # This is a workaround to handle if folding the causes the
            # cursor index to go out of bounds.
            self.nav.page_index, self.nav.cursor_index = current_index, 0

    @SubmissionController.register('r', curses.KEY_F5)
    def refresh_content(self):
        """
        Reset the content generator to force comments to re-download.
        """
        url = self.content.name
        self.content = SubmissionContent.from_url(self.reddit, url, self.loader)
        self.nav.page_index, self.nav.cursor_index = -1, 0
        self.nav.inverted = False

    @SubmissionController.register('o')
    def open_link(self):
        """
        Open the selected link in a webbrowser tab.
        """
        # Always open the page for the submission
        # May want to expand at some point to open comment permalinks
        url = self.content.get(-1)['permalink']
        open_browser(url)

    @SubmissionController.register('c')
    def add_comment(self):
        """
        Add a comment on the submission if a header is selected.
        Reply to a comment if the comment is selected.
        """

        if not self.reddit.is_logged_in():
            display_message(self.stdscr, ["Login to reply"])
            return

        data = self.content.get(self.nav.absolute_index)
        if data['type'] not in ('Comment', 'Submission'):
            curses.flash()
            return

        # Fill the bottom half of the screen with the comment box
        n_rows, n_cols = self.stdscr.getmaxyx()
        box_height = n_rows // 2
        attr = curses.A_BOLD | Color.CYAN

        for x in range(n_cols):
            y = box_height - 1
            # http://bugs.python.org/issue21088
            if (sys.version_info.major,
                sys.version_info.minor,
                sys.version_info.micro) == (3, 4, 0):
                x, y = y, x

            self.stdscr.addch(y, x, curses.ACS_HLINE, attr)

        prompt = 'Enter comment: ESC to cancel, Ctrl+g to submit'
        scol = max(0, (n_cols // 2) - (len(prompt) // 2))
        self.stdscr.addnstr(box_height-1, scol, prompt, n_cols-scol, attr)
        self.stdscr.refresh()

        window = self.stdscr.derwin(n_rows-box_height, n_cols, box_height, 0)
        window.attrset(Color.CYAN)

        comment_text = text_input(window, allow_resize=False)
        if comment_text is None:
            return

        try:
            if data['type'] == 'Submission':
                data['object'].add_comment(comment_text)
            else:
                data['object'].reply(comment_text)
        except praw.errors.APIException as e:
            display_message(self.stdscr, [e.message])
        else:
            time.sleep(0.5)
            self.refresh_content()

    def _draw_item(self, win, data, inverted=False):

        if data['type'] == 'MoreComments':
            return self._draw_more_comments(win, data)
        elif data['type'] == 'HiddenComment':
            return self._draw_more_comments(win, data)
        elif data['type'] == 'Comment':
            return self._draw_comment(win, data, inverted=inverted)
        else:
            return self._draw_submission(win, data)

    @staticmethod
    def _draw_comment(win, data, inverted=False):

        n_rows, n_cols = win.getmaxyx()
        n_cols -= 1

        # Handle the case where the window is not large enough to fit the text.
        valid_rows = range(0, n_rows)
        offset = 0 if not inverted else -(data['n_rows'] - n_rows)

        row = offset
        if row in valid_rows:

            text = clean('{author} '.format(**data))
            attr = curses.A_BOLD
            attr |= (Color.BLUE if not data['is_author'] else Color.GREEN)
            win.addnstr(row, 1, text, n_cols-1, attr)

            if data['flair']:
                text = clean('{flair} '.format(**data))
                attr = curses.A_BOLD | Color.YELLOW
                win.addnstr(text, n_cols-win.getyx()[1], attr)

            if data['likes'] is None:
                text, attr = BULLET, curses.A_BOLD
            elif data['likes']:
                text, attr = UARROW, (curses.A_BOLD | Color.GREEN)
            else:
                text, attr = DARROW, (curses.A_BOLD | Color.RED)
            win.addnstr(text, n_cols-win.getyx()[1], attr)

            text = clean(' {score} {created}'.format(**data))
            win.addnstr(text, n_cols-win.getyx()[1])

        n_body = len(data['split_body'])
        for row, text in enumerate(data['split_body'], start=offset+1):
            if row in valid_rows:
                text = clean(text)
                win.addnstr(row, 1, text, n_cols-1)

        # Unfortunately vline() doesn't support custom color so we have to
        # build it one segment at a time.
        attr = Color.get_level(data['level'])
        for y in range(n_rows):
            x = 0
            # http://bugs.python.org/issue21088
            if (sys.version_info.major,
                sys.version_info.minor,
                sys.version_info.micro) == (3, 4, 0):
                x, y = y, x

            win.addch(y, x, curses.ACS_VLINE, attr)

        return (attr | curses.ACS_VLINE)

    @staticmethod
    def _draw_more_comments(win, data):

        n_rows, n_cols = win.getmaxyx()
        n_cols -= 1

        text = clean('{body}'.format(**data))
        win.addnstr(0, 1, text, n_cols-1)
        text = clean(' [{count}]'.format(**data))
        win.addnstr(text, n_cols-win.getyx()[1], curses.A_BOLD)

        # Unfortunately vline() doesn't support custom color so we have to
        # build it one segment at a time.
        attr = Color.get_level(data['level'])
        win.addch(0, 0, curses.ACS_VLINE, attr)

        return (attr | curses.ACS_VLINE)

    @staticmethod
    def _draw_submission(win, data):

        n_rows, n_cols = win.getmaxyx()
        n_cols -= 3 # one for each side of the border + one for offset

        # Don't print at all if there is not enough room to fit the whole sub
        if data['n_rows'] > n_rows:
            win.addnstr(0, 0, '(Not enough space to display)', n_cols)
            return

        for row, text in enumerate(data['split_title'], start=1):
            text = clean(text)
            win.addnstr(row, 1, text, n_cols, curses.A_BOLD)

        row = len(data['split_title']) + 1
        attr = curses.A_BOLD | Color.GREEN
        text = clean('{author}'.format(**data))
        win.addnstr(row, 1, text, n_cols, attr)
        attr = curses.A_BOLD | Color.YELLOW
        text = clean(' {flair}'.format(**data))
        win.addnstr(text, n_cols-win.getyx()[1], attr)
        text = clean(' {created} {subreddit}'.format(**data))
        win.addnstr(text, n_cols-win.getyx()[1])

        row = len(data['split_title']) + 2
        attr = curses.A_UNDERLINE | Color.BLUE
        text = clean('{url}'.format(**data))
        win.addnstr(row, 1, text, n_cols, attr)

        offset = len(data['split_title']) + 3
        for row, text in enumerate(data['split_text'], start=offset):
            text = clean(text)
            win.addnstr(row, 1, text, n_cols)

        row = len(data['split_title']) + len(data['split_text']) + 3
        text = clean('{score} {comments}'.format(**data))
        win.addnstr(row, 1, text, n_cols, curses.A_BOLD)

        win.border()