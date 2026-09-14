import copy
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch
import uuid

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from annie.prayer_times import (PrayerSettings, PrayerStore, DISPLAY_TIMES, fetch_schedule,
                               next_prayer, today_schedule, refresh_due)

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def response_for(day, school=1):
    hours = ['04:00', '05:45', '12:10', '16:35' if school else '15:40', '18:35', '20:30']
    raw = {'code': 200, 'data': {
        'timings': {name: f'{day.isoformat()}T{hour}:00+05:00' for name, hour in zip(DISPLAY_TIMES, hours)},
        'meta': {'timezone': 'Asia/Almaty'},
        'date': {'gregorian': {'date': day.strftime('%d-%m-%Y')},
                 'hijri': {'day': '1', 'month': {'en': 'Rabi al-thani'}, 'year': '1448'}}}}
    response = Mock()
    response.json.return_value = raw
    return response


def fake_get(url, params, timeout):
    day = datetime.strptime(url.rsplit('/', 1)[-1], '%d-%m-%Y').date()
    return response_for(day, params['school'])


def sample_data(settings=None):
    return fetch_schedule(settings or PrayerSettings(city='Astana', country='Kazakhstan'), now=NOW, get=fake_get)


class PrayerCalculationTests(unittest.TestCase):
    def test_four_madhhabs_map_to_two_asr_conventions(self):
        self.assertEqual([PrayerSettings(madhhab=name).school for name in
                          ('hanafi', 'shafii', 'maliki', 'hanbali')], [1, 0, 0, 0])

    def test_request_has_city_school_method_iso_and_timeout_no_geolocation(self):
        get = Mock(side_effect=fake_get)
        settings = PrayerSettings(city='Astana', country='Kazakhstan', madhhab='hanafi', method=1)
        result = fetch_schedule(settings, now=NOW, get=get)
        self.assertEqual(get.call_count, 2)
        for call in get.call_args_list:
            self.assertTrue(call.args[0].startswith('https://api.aladhan.com/v1/timingsByCity/'))
            self.assertEqual(call.kwargs['params']['school'], 1)
            self.assertEqual(call.kwargs['params']['method'], 1)
            self.assertEqual(call.kwargs['params']['iso8601'], 'true')
            self.assertEqual(call.kwargs['timeout'], (5, 15))
        self.assertEqual(result['timezone'], 'Asia/Almaty')

    def test_after_isha_uses_actual_tomorrow_fajr(self):
        data = sample_data()
        now = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)  # 23:00 Astana
        when, name = next_prayer(data, now)
        self.assertEqual(name, 'Fajr')
        self.assertEqual(when.isoformat(), '2026-09-13T04:00:00+05:00')
        self.assertEqual((when - now).total_seconds(), 5 * 3600)

    def test_sunrise_is_not_next_prayer(self):
        data = sample_data()
        now = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)  # 05:00, after Fajr
        self.assertEqual(next_prayer(data, now)[1], 'Dhuhr')

    def test_clock_uses_city_date_not_utc_date(self):
        data = sample_data()
        now = datetime(2026, 9, 12, 20, 0, tzinfo=timezone.utc)  # 13th in Astana
        self.assertEqual(today_schedule(data, now)['date'], '2026-09-13')
        self.assertTrue(refresh_due(data, now))
        self.assertFalse(refresh_due(data, NOW))

    def test_expired_cache_never_pretends_yesterday_is_today(self):
        data = sample_data()
        self.assertIsNone(today_schedule(data, NOW + timedelta(days=2)))
        self.assertIsNone(next_prayer(data, NOW + timedelta(days=2)))

    def test_manual_adjustments_apply_once(self):
        settings = PrayerSettings(city='Astana', country='Kazakhstan', adjustments={'Asr': 5})
        data = sample_data(settings)
        self.assertIn('T16:40:00', data['days'][0]['times']['Asr'])

    def test_malformed_missing_timezone_or_bad_order_is_rejected(self):
        settings = PrayerSettings(city='Astana', country='Kazakhstan')
        for bad in ('not a time', '2026-09-12T04:00:00', '2026-09-12T23:00:00+05:00'):
            response = response_for(NOW.date())
            response.json.return_value['data']['timings']['Fajr'] = bad
            with self.assertRaises(ValueError):
                fetch_schedule(settings, now=NOW, get=Mock(return_value=response))

    def test_cancellation_prevents_network_request(self):
        get = Mock()
        with self.assertRaises(InterruptedError):
            fetch_schedule(PrayerSettings(city='Astana', country='Kazakhstan'),
                           get=get, cancelled=lambda: True)
        get.assert_not_called()

    def test_failure_on_second_day_does_not_overwrite_existing_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PrayerStore(folder)
            settings = PrayerSettings(city='Astana', country='Kazakhstan')
            original = sample_data(settings)
            store.save_cache(original)
            with self.assertRaises(OSError):
                fetch_schedule(settings, now=NOW,
                               get=Mock(side_effect=[response_for(NOW.date()), OSError('offline')]))
            self.assertEqual(store.cache(settings), original)

    def test_settings_changes_invalidate_cache_but_layout_changes_do_not(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PrayerStore(folder)
            settings = PrayerSettings(city='Astana', country='Kazakhstan')
            store.save_settings(settings)
            store.save_cache(sample_data(settings))
            restored = store.settings()
            restored.compact = True
            self.assertIsNotNone(store.cache(restored))
            restored.madhhab = 'shafii'
            self.assertIsNone(store.cache(restored))
            restored.madhhab = 'hanafi'
            restored.city = 'Almaty'
            self.assertIsNone(store.cache(restored))

    def test_default_profile_has_no_location_or_network_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = PrayerStore(folder).settings()
            self.assertEqual(settings.city, '')
            with self.assertRaises(ValueError):
                settings.validate()

    def test_timezone_offset_change_preserves_elapsed_countdown(self):
        data = sample_data()
        # A future prayer with a different offset is compared as an instant.
        data['days'][1]['times']['Fajr'] = '2026-09-13T04:00:00+04:00'
        now = datetime(2026, 9, 12, 18, tzinfo=timezone.utc)
        self.assertEqual((next_prayer(data, now)[0] - now).total_seconds(), 6 * 3600)


class PrayerWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        from annie.gui.prayer_widget import PrayerWidget
        self.temporary = tempfile.TemporaryDirectory()
        self.store = PrayerStore(self.temporary.name)
        self.store.save_settings(PrayerSettings(city='Astana', country='Kazakhstan'))
        self.store.save_cache(sample_data())
        self.widget = PrayerWidget(self.store, start_network=False)
        self.widget.setAttribute(Qt.WA_DontShowOnScreen)
        self.widget.show()
        self.app.processEvents()
        self.widget.tick(NOW)

    def tearDown(self):
        self.widget.shutdown(lambda: None)
        self.widget.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def test_card_shows_next_prayer_and_six_times(self):
        self.assertEqual(self.widget.next_label.text(), 'До Асра')
        self.assertEqual(self.widget.countdown.text(), '01:35:00')
        self.assertEqual(self.widget.tiles['Asr'][1].text(), '16:35')
        self.assertTrue(self.widget.tiles['Asr'][0].property('next'))
        self.assertEqual(len(self.widget.tiles), 6)

    def test_compact_mode_animates_and_persists(self):
        self.widget.toggle_size()
        deadline = time.monotonic() + 2
        while self.widget._animation.state() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(self.widget.settings.compact)
        self.assertFalse(self.widget.times_panel.isVisible())
        self.assertTrue(self.store.settings().compact)
        self.assertEqual(self.widget.width(), 250)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows desktop surface')
    def test_windows_surface_remains_non_layered_across_pin_changes(self):
        self.assertFalse(self.widget.testAttribute(Qt.WA_TranslucentBackground))
        self.assertTrue(self.widget.autoFillBackground())
        self.assertFalse(self.widget.mask().isEmpty())
        self.widget.set_pinned(True)
        self.widget.set_pinned(False)
        self.assertFalse(self.widget.testAttribute(Qt.WA_TranslucentBackground))

    def test_stale_schedule_is_cleared_in_ui(self):
        self.widget.tick(NOW + timedelta(days=2))
        self.assertEqual(self.widget.countdown.text(), '—:—:—')
        self.assertEqual(self.widget.tiles['Asr'][1].text(), '—:—')
        self.assertIn('Нет данных на сегодня', self.widget.footer.text())

    def test_widget_is_tool_window_not_taskbar_app(self):
        self.assertEqual(self.widget.windowType(), Qt.Tool)
        self.assertFalse(self.widget.windowFlags() & Qt.WindowStaysOnTopHint)

    def test_pin_preference_locks_dragging_and_disables_always_on_top(self):
        self.widget.settings.always_on_top = True
        self.widget.set_pinned(True)  # Hidden test surfaces never touch Explorer.
        if sys.platform == 'win32':
            self.assertTrue(self.store.settings().desktop_pinned)
            self.assertFalse(self.store.settings().always_on_top)
            event = Mock()
            event.button.return_value = Qt.LeftButton
            self.widget.mousePressEvent(event)
            event.globalPos.assert_not_called()
            self.assertIsNone(self.widget._drag)
            self.widget.set_pinned(False)
            self.assertFalse(self.store.settings().desktop_pinned)

    def test_pin_and_appearance_do_not_invalidate_prayer_cache(self):
        settings = self.store.settings()
        signature = settings.signature
        settings.desktop_pinned = True
        settings.compact = True
        settings.validate()
        self.assertEqual(settings.signature, signature)
        self.assertIsNotNone(self.store.cache(settings))

    def test_glass_card_contains_six_distinct_vector_symbols(self):
        from annie.gui.prayer_card import PrayerIcon
        icons = [tile.findChild(PrayerIcon) for tile, value in self.widget.tiles.values()]
        self.assertEqual({icon.prayer for icon in icons}, set(DISPLAY_TIMES))
        self.assertEqual(self.widget.summary_countdown.text(), self.widget.countdown.text())

    def test_compact_city_avoids_crowding_hijri_date(self):
        self.widget.settings.city = 'Astana, Esil District'
        self.widget.settings.compact = True
        self.widget.tick(NOW)
        self.assertEqual(self.widget.location.text(), 'Астана')
        self.assertIn('Esil District', self.widget.location.toolTip())

    def wait_job(self):
        deadline = time.monotonic() + 3
        while self.widget._worker is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(self.widget._worker)

    def test_fetch_runs_in_background_and_shutdown_waits_for_worker(self):
        finished = Mock()

        def slow_fetch(*args, **kwargs):
            time.sleep(.15)
            return sample_data()

        with patch('annie.gui.prayer_widget.fetch_schedule', side_effect=slow_fetch):
            self.widget._network = True
            self.widget.refresh(True)
            self.assertIsNotNone(self.widget._worker)
            self.widget.shutdown(finished)
            finished.assert_not_called()
            self.wait_job()
            finished.assert_called_once()

    def test_network_failure_retains_cached_times(self):
        original = copy.deepcopy(self.widget.data)
        with patch('annie.gui.prayer_widget.fetch_schedule', side_effect=OSError('offline')):
            self.widget._network = True
            self.widget.refresh(True)
            self.wait_job()
        self.widget.tick(NOW)
        self.assertEqual(self.widget.data, original)
        self.assertEqual(self.widget.tiles['Asr'][1].text(), '16:35')
        self.assertIn('Обновление не удалось', self.widget.footer.text())

    def test_cached_day_does_not_make_repeated_network_requests(self):
        with patch('annie.gui.prayer_widget.refresh_due', return_value=False), \
             patch('annie.gui.prayer_widget.PrayerFetchThread') as thread:
            self.widget._network = True
            for _ in range(10):
                self.widget.tick(NOW)
            thread.assert_not_called()

    def test_single_instance_lock_reuses_existing_widget(self):
        from annie.prayer_widget_main import WidgetInstance
        name = 'prayer-test-' + uuid.uuid4().hex
        owner, duplicate = WidgetInstance(self.app, name), WidgetInstance(self.app, name)
        shown = []
        owner.show_requested.connect(lambda: shown.append(True))
        try:
            self.assertTrue(owner.acquire())
            self.assertFalse(duplicate.acquire())
            QTest.qWait(100)
            self.assertEqual(shown, [True])
        finally:
            owner.close()
            duplicate.close()

    def test_widget_bootstrap_does_not_import_recording_or_voice(self):
        result = subprocess.run([sys.executable, '-B', '-c',
            "import sys; import annie.prayer_widget_main; import annie.gui.prayer_widget; "
            "assert not any(n in sys.modules for n in ['annie.whisper_runtime','annie.workstation_main','annie.live','sounddevice'])"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mac_login_item_contains_only_widget_and_preserves_other_owner(self):
        from annie import prayer_startup
        with tempfile.TemporaryDirectory() as folder, patch.object(sys, 'platform', 'darwin'), \
             patch.object(Path, 'home', return_value=Path(folder)):
            prayer_startup.set_enabled(True)
            self.assertTrue(prayer_startup.enabled())
            self.assertEqual(prayer_startup.agent()['ProgramArguments'][-1], '--prayer-widget')
            self.assertNotIn('--watch', prayer_startup.agent()['ProgramArguments'])
            with patch.object(prayer_startup, 'arguments', return_value=['/other/app', '--prayer-widget']):
                self.assertFalse(prayer_startup.enabled())
                with self.assertRaises(RuntimeError):
                    prayer_startup.set_enabled(True)
                prayer_startup.set_enabled(False)
                self.assertTrue(prayer_startup.agent_path().exists())
            prayer_startup.set_enabled(False)
            self.assertFalse(prayer_startup.agent_path().exists())


class DesktopSurfaceTests(unittest.TestCase):
    def test_selects_visible_outer_desktop_host(self):
        from annie.desktop_pin import find_desktop_host
        gui = Mock()
        gui.EnumWindows.side_effect = lambda callback, value: callback(10, value)
        gui.GetClassName.return_value = 'WorkerW'
        gui.FindWindowEx.side_effect = lambda parent, after, name, title: {
            (10, 'SHELLDLL_DefView'): 20, (20, 'SysListView32'): 30}.get((parent, name), 0)
        gui.IsWindowVisible.return_value = True
        gui.GetClientRect.return_value = (0, 0, 1920, 1080)
        self.assertEqual(find_desktop_host(gui), 10)
        gui.IsWindowVisible.side_effect = lambda hwnd: hwnd != 10
        self.assertIsNone(find_desktop_host(gui))
        gui.IsWindowVisible.side_effect = None
        gui.FindWindowEx.side_effect = lambda *args: 0
        self.assertIsNone(find_desktop_host(gui))


class DesktopPinTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(sys, 'platform', 'win32'))
        self.state = {'parent': 0, -16: 0x80000000, -20: 0x80}
        self.gui = Mock()
        self.gui.IsWindow.side_effect = lambda hwnd: hwnd in (11, 99)
        self.gui.GetParent.side_effect = lambda hwnd: self.state['parent']
        self.gui.GetWindowRect.return_value = (140, 200, 620, 426)
        self.gui.GetWindowLong.side_effect = lambda hwnd, key: self.state[key]
        self.gui.SetWindowLong.side_effect = lambda hwnd, key, value: self.state.update({key: value})
        self.gui.SetParent.side_effect = lambda hwnd, parent: self.state.update(parent=parent)
        self.gui.ScreenToClient.side_effect = lambda hwnd, point: (point[0] - 100, point[1] - 50)
        con = types.SimpleNamespace(GWL_STYLE=-16, GWL_EXSTYLE=-20, WS_POPUP=0x80000000,
             WS_CHILD=0x40000000, WS_EX_TOOLWINDOW=0x80, WS_EX_APPWINDOW=0x40000,
             WS_EX_TOPMOST=8, HWND_TOP=0, HWND_NOTOPMOST=-2, SWP_NOACTIVATE=16,
             SWP_FRAMECHANGED=32, SWP_SHOWWINDOW=64)
        process = types.SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, 123))
        self.stack.enter_context(patch.dict(sys.modules, {'win32gui': self.gui,
                                                        'win32con': con, 'win32process': process}))
        self.stack.enter_context(patch('annie.desktop_pin.find_desktop_host', return_value=99))
        proc = self.stack.enter_context(patch('psutil.Process'))
        proc.return_value.name.return_value = 'explorer.exe'
        self.dll = Mock()
        self.dll.AreDpiAwarenessContextsEqual.return_value = True
        self.stack.enter_context(patch('ctypes.WinDLL', return_value=self.dll, create=True))
        from annie.desktop_pin import DesktopPin
        widget = Mock()
        widget.winId.return_value = 11
        self.pin = DesktopPin(widget)

    def test_pin_attaches_our_hwnd_and_unpin_restores_native_styles(self):
        original = self.state.copy()
        self.pin.attach()
        self.assertTrue(self.pin.attached)
        self.assertEqual(self.state['parent'], 99)
        self.assertTrue(self.state[-16] & 0x40000000)
        self.assertFalse(self.state[-16] & 0x80000000)
        self.assertEqual(self.gui.SetWindowPos.call_args.args[2:4], (40, 150))
        self.pin.detach()
        self.assertFalse(self.pin.attached)
        self.assertEqual(self.state, original)
        self.assertTrue(all(call.args[0] == 11 for call in self.gui.SetWindowLong.call_args_list))

    def test_failed_attach_rolls_back_without_changing_explorer(self):
        original = self.state.copy()
        self.gui.SetWindowPos.side_effect = [OSError('native failure'), None]
        with self.assertRaises(OSError):
            self.pin.attach()
        self.assertEqual(self.state, original)
        self.assertFalse(self.pin.attached)

    def test_dpi_mismatch_is_rejected_before_mutating_any_window(self):
        self.dll.AreDpiAwarenessContextsEqual.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'DPI'):
            self.pin.attach()
        self.gui.SetParent.assert_not_called()
        self.gui.SetWindowLong.assert_not_called()

    def test_missing_desktop_is_not_faked_with_always_on_top(self):
        with patch('annie.desktop_pin.find_desktop_host', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                self.pin.attach()
        self.gui.SetWindowLong.assert_not_called()

    def test_layered_surface_is_rejected_before_parenting(self):
        self.state[-20] |= 0x80000
        with self.assertRaisesRegex(RuntimeError, 'Transparent'):
            self.pin.attach()
        self.gui.SetParent.assert_not_called()
        self.gui.SetWindowLong.assert_not_called()


if __name__ == '__main__':
    unittest.main()
