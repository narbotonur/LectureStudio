"""Local flashcard review dialog."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from annie.flashcard_review import CardReviews
from annie.gui.design import apply_theme, label


class FlashcardSession(QDialog):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.resize(590, 400)
        self.setWindowTitle('Review flashcards')
        self.store = CardReviews(root)
        self.queue = iter(list(self.store.due()))
        box = QVBoxLayout(self)
        self.source = label('', 'muted')
        self.front = label('', 'section')
        self.back = label('')
        self.status = label('')
        for field in (self.source, self.front, self.back, self.status):
            field.setTextFormat(Qt.PlainText)
            field.setWordWrap(True)
            field.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.addWidget(field)
        box.addStretch(1)
        self.reveal = QPushButton('Show answer')
        self.reveal.clicked.connect(self._show_answer)
        box.addWidget(self.reveal)
        row = QHBoxLayout()
        self.rating_buttons = []
        for rating, text in enumerate(('Again', 'Hard', 'Good', 'Easy'), 1):
            button = QPushButton(text)
            button.clicked.connect(lambda _, choice=rating: self._rate(choice))
            self.rating_buttons.append(button)
            row.addWidget(button)
        box.addLayout(row)
        self._next()
        apply_theme(self)

    def _next(self):
        self.active = next(self.queue, None)
        self.source.setText(self.active['title'] if self.active else '')
        self.front.setText(self.active['front'] if self.active else 'No flashcards are due.')
        self.back.clear()
        self.reveal.setEnabled(self.active is not None)
        for button in self.rating_buttons:
            button.setEnabled(False)

    def _show_answer(self):
        self.back.setText(self.active['back'])
        self.reveal.setEnabled(False)
        for button in self.rating_buttons:
            button.setEnabled(True)

    def _rate(self, choice):
        try:
            due = self.store.rate(self.active['id'], choice)
        except (ImportError, OSError, ValueError) as exc:
            self.status.setText(f'Could not save the review: {exc}')
            return
        self.status.setText(f'Next review {due.astimezone():%d %b, %H:%M}.')
        self._next()
