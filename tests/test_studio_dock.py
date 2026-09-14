import unittest
from unittest.mock import patch

from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from annie.gui.studio_dock import StudioDock


class DockBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dock = StudioDock()
        self.dock.setAttribute(Qt.WA_DontShowOnScreen)
        self.dock.present()
        QTest.qWait(500)

    def tearDown(self):
        self.dock.hide_immediately()
        self.dock.deleteLater()
        self.app.processEvents()

    def test_three_seconds_away_collapses_and_click_expands_without_opening_studio(self):
        restored = []
        self.dock.restore_requested.connect(lambda: restored.append(True))
        with patch('annie.gui.studio_dock.QCursor.pos', return_value=QPoint(-10000, -10000)):
            self.dock.leaveEvent(QEvent(QEvent.Leave))
            QTest.qWait(2100)
            self.assertFalse(self.dock._compact)
            QTest.qWait(1250)
        self.assertTrue(self.dock._compact)
        self.assertEqual(self.dock.size().width(), 68)
        self.assertFalse(self.dock.links_panel.isVisible())
        self.assertFalse(self.dock.restore_button.isVisible())
        self.dock.enterEvent(QEvent(QEvent.Enter))
        self.assertTrue(self.dock._compact)  # Hover alone must not expand it.
        QTest.mouseClick(self.dock, Qt.LeftButton, pos=self.dock.rect().center())
        QTest.qWait(400)
        self.assertFalse(self.dock._compact)
        self.assertTrue(self.dock.links_panel.isVisible())
        self.assertEqual(restored, [])

    def test_hover_cancels_pending_collapse(self):
        self.dock.leaveEvent(QEvent(QEvent.Leave))
        self.assertTrue(self.dock._collapse_timer.isActive())
        self.dock.enterEvent(QEvent(QEvent.Enter))
        self.assertFalse(self.dock._collapse_timer.isActive())
        self.assertFalse(self.dock._compact)

    def test_side_edges_and_corners_snap_vertical_and_remain_anchored(self):
        area = QRect(0, 0, 1920, 1080)
        for rect, edge in ((QRect(15, 12, 550, 148), 'left'),
                           (QRect(1350, 12, 550, 148), 'right'),
                           (QRect(15, 910, 550, 148), 'left'),
                           (QRect(1350, 910, 550, 148), 'right')):
            self.assertEqual(StudioDock.edge_for(rect, area), edge)
        with patch.object(self.dock, '_screen_area', return_value=area):
            self.dock.setGeometry(1350, 910, 550, 148)
            self.dock._transition_layout(adapt_edge=True)
            QTest.qWait(400)
            self.assertTrue(self.dock._vertical)
            self.assertEqual(self.dock.geometry().right(), area.right() - 6)
            self.assertEqual(self.dock.geometry().bottom(), area.bottom() - 6)
            self.dock._compact = True
            self.dock._transition_layout()
            QTest.qWait(400)
            self.dock.set_recording(True)
            QTest.qWait(400)
            self.assertEqual((self.dock.width(), self.dock.height()), (68, 178))
            self.assertTrue(self.dock.meter.isVisible())
            self.assertEqual(self.dock.geometry().right(), area.right() - 6)
            self.assertEqual(self.dock.geometry().bottom(), area.bottom() - 6)
            self.dock.expand()
            QTest.qWait(400)
            self.assertEqual(self.dock.geometry().right(), area.right() - 6)
            self.assertEqual(self.dock.geometry().bottom(), area.bottom() - 6)

    def test_top_bottom_are_horizontal_and_snap(self):
        area = QRect(-1920, 0, 1920, 1080)
        with patch.object(self.dock, '_screen_area', return_value=area):
            for y, edge in ((12, 'top'), (910, 'bottom')):
                self.dock.setGeometry(-1400, y, 550, 148)
                self.assertEqual(StudioDock.edge_for(self.dock.geometry(), area), edge)
                self.dock._transition_layout(adapt_edge=True)
                QTest.qWait(400)
                self.assertFalse(self.dock._vertical)
                if edge == 'top':
                    self.assertEqual(self.dock.y(), 6)
                else:
                    self.assertEqual(self.dock.geometry().bottom(), area.bottom() - 6)


if __name__ == '__main__':
    unittest.main()
