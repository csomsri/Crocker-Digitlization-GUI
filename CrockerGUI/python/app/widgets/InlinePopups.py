"""Non-window calendars, tooltips, and text editing menus."""
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, QObject
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QCalendarWidget, QDateEdit, QWidget, QAbstractItemView,
    QLineEdit, QTextEdit, QPlainTextEdit, QScrollBar, QAbstractSlider,
)


class InlinePopup(QFrame):
    def __init__(self, anchor):
        super().__init__(anchor.window())
        self.anchor = anchor
        self._dismissed = False
        self.previous_focus = QApplication.focusWidget()
        self.setObjectName('inlinePopup')
        self.setStyleSheet(
            (Path(__file__).resolve().parents[1] / 'theme' / 'dialogs.qss').read_text(encoding='utf-8')
            + 'QFrame#inlinePopup { background: #142235; border: 1px solid #52769c; border-radius: 8px; }'
            + 'QCalendarWidget QWidget { background: #142235; color: #e7eef8; }'
            + 'QCalendarWidget QAbstractItemView { selection-background-color: #28639a; selection-color: white; }')
        self.setAttribute(Qt.WA_StyledBackground)

    def present(self, position=None):
        self.adjustSize()
        host = self.parentWidget()
        self.resize(min(self.width(), host.width()), min(self.height(), host.height()))
        point = position or self.anchor.mapTo(host, QPoint(0, self.anchor.height()))
        self.move(max(0, min(point.x(), host.width()-self.width())),
                  max(0, min(point.y(), host.height()-self.height())))
        QApplication.instance().installEventFilter(self)
        self.show()
        self.raise_()

    def dismiss(self):
        if self._dismissed:
            return
        self._dismissed = True
        QApplication.instance().removeEventFilter(self)
        self.hide()
        from shiboken6 import isValid
        if self.previous_focus is not None and isValid(self.previous_focus):
            self.previous_focus.setFocus(Qt.PopupFocusReason)
        self.deleteLater()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab):
            self.dismiss()
            return True
        if event.type() == QEvent.MouseButtonPress and not self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint())):
            self.dismiss()
        if watched is self.parent() and event.type() in (QEvent.Resize, QEvent.Hide, QEvent.WindowDeactivate):
            self.dismiss()
        return False


class ScreenSafeDateEdit(QDateEdit):
    def _show_calendar(self):
        popup = InlinePopup(self)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(12, 12, 12, 12)
        calendar = QCalendarWidget()
        calendar.setNavigationBarVisible(False)  # Native month menus are avoided too.
        calendar.setGridVisible(False)
        calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        calendar.setMinimumSize(320, 240)
        from PySide6.QtGui import QColor, QTextCharFormat
        weekend = QTextCharFormat()
        weekend.setForeground(QColor('#b9cce1'))
        calendar.setWeekdayTextFormat(Qt.Saturday, weekend)
        calendar.setWeekdayTextFormat(Qt.Sunday, weekend)
        calendar.setMinimumDate(self.minimumDate())
        calendar.setMaximumDate(self.maximumDate())
        calendar.setSelectedDate(self.date())
        header = QHBoxLayout()
        previous, following = QPushButton('Previous'), QPushButton('Next')
        previous.setAccessibleName('Previous month')
        following.setAccessibleName('Next month')
        title = QLabel()
        title.setAlignment(Qt.AlignCenter)
        header.addWidget(previous)
        header.addWidget(title, 1)
        header.addWidget(following)
        previous.clicked.connect(calendar.showPreviousMonth)
        following.clicked.connect(calendar.showNextMonth)
        def month_changed(year, month):
            from PySide6.QtCore import QDate
            title.setText(QDate(year, month, 1).toString('MMMM yyyy'))
        calendar.currentPageChanged.connect(month_changed)
        month_changed(calendar.yearShown(), calendar.monthShown())
        layout.addLayout(header)
        layout.addWidget(calendar)
        def select(date):
            self.setDate(date)
            popup.dismiss()
        calendar.clicked.connect(select)
        calendar.activated.connect(select)
        popup.present()
        calendar.setFocus(Qt.PopupFocusReason)

    def mousePressEvent(self, event):
        if self.calendarPopup() and event.button() == Qt.LeftButton and event.position().x() >= self.width()-32:
            self._show_calendar()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self.calendarPopup() and (event.key() == Qt.Key_F4 or
                event.key() == Qt.Key_Down and event.modifiers() & Qt.AltModifier):
            self._show_calendar()
            event.accept()
            return
        super().keyPressEvent(event)


class PopupService(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.label = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide_tip)
        app.installEventFilter(self)

    def hide_tip(self):
        from shiboken6 import isValid
        if self.label is not None and isValid(self.label):
            self.label.hide()
            self.label.deleteLater()
        self.label = None
        self.timer.stop()

    def show_tip(self, position, text, widget, duration=7000):
        self.hide_tip()
        if not text or widget is None:
            return
        host = widget.window()
        label = self.label = QLabel(text, host)
        label.setObjectName('inlineToolTip')
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        label.setWordWrap(True)
        label.setStyleSheet('QLabel { background: #20334b; color: #edf5ff; border: 1px solid #567a9f; border-radius: 6px; padding: 8px 10px; font: 12px "Segoe UI"; }')
        label.setMaximumWidth(min(480, host.width()))
        label.adjustSize()
        point = host.mapFromGlobal(position) + QPoint(12, 18)
        label.move(max(0, min(point.x(), host.width()-label.width())),
                   max(0, min(point.y(), host.height()-label.height())))
        label.show()
        label.raise_()
        self.timer.start(duration if duration > 0 else 7000)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.ToolTip and isinstance(watched, QWidget):
            text = watched.toolTip()
            view = watched.parentWidget()
            if not text and isinstance(view, QAbstractItemView):
                text = view.indexAt(event.pos()).data(Qt.ToolTipRole) or view.toolTip()
            self.show_tip(event.globalPos(), text, watched, watched.toolTipDuration())
            event.accept()
            return True
        if event.type() == QEvent.ContextMenu:
            actions = []
            if isinstance(watched, (QLineEdit, QTextEdit, QPlainTextEdit)):
                actions = [(text, action, not watched.isReadOnly() or text in ('Copy', 'Select all'))
                           for text, action in [('Undo', watched.undo), ('Redo', watched.redo),
                                ('Cut', watched.cut), ('Copy', watched.copy),
                                ('Paste', watched.paste), ('Select all', watched.selectAll)]]
            elif isinstance(watched, QScrollBar):
                actions = [(text, lambda action=action: watched.triggerAction(action), True)
                           for text, action in [('Start', QAbstractSlider.SliderToMinimum),
                                ('Page back', QAbstractSlider.SliderPageStepSub),
                                ('Page forward', QAbstractSlider.SliderPageStepAdd),
                                ('End', QAbstractSlider.SliderToMaximum)]]
            elif isinstance(watched, QLabel) and watched.textInteractionFlags() & Qt.TextSelectableByMouse:
                actions = [
                    ('Copy', lambda: QApplication.clipboard().setText(watched.selectedText()), watched.hasSelectedText()),
                    ('Select all', lambda: watched.setSelection(0, len(watched.text())), True),
                ]
            if actions:
                popup = InlinePopup(watched)
                layout = QVBoxLayout(popup)
                layout.setContentsMargins(6, 6, 6, 6)
                for text, action, enabled in actions:
                    button = QPushButton(text)
                    button.setEnabled(enabled)
                    button.clicked.connect(lambda checked=False, action=action: (action(), popup.dismiss()))
                    layout.addWidget(button)
                popup.present(watched.window().mapFromGlobal(event.globalPos()))
                popup.findChild(QPushButton).setFocus(Qt.PopupFocusReason)
                return True
        if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Leave, QEvent.WindowDeactivate):
            self.hide_tip()
        return False


def install_popup_service(app=None):
    app = app or QApplication.instance()
    if not hasattr(app, '_inline_popup_service'):
        app._inline_popup_service = PopupService(app)
    return app._inline_popup_service


class InlineToolTip:
    @staticmethod
    def showText(position, text, widget=None):
        install_popup_service().show_tip(position, text, widget or QApplication.activeWindow())

    @staticmethod
    def hideText():
        install_popup_service().hide_tip()
