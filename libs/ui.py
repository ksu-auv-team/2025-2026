"""
AUV Control TUI
===============

A Textual TUI for monitoring and controlling an Autonomous Underwater Vehicle.
Modern dark-mode design with electric-blue accent, rounded panels, and animated
status indicators.

Layout:
    ╭─── SERVICES ────────────╮  ╭─── TELEMETRY ──────────────────╮
    │ db          ⬤  pid 123  │  │  Accelerometer  x:+0.01 ...    │
    │ hardware_if ○  pid —    │  │  [plotext graph]                │
    │ movement    ⬤  pid 456  │  │  Gyroscope  ...                 │
    │ camera      ○  pid —    │  │  [plotext graph]                │
    │ ai          ○  pid —    │  │  Depth / Power ...              │
    ╰─────────────────────────╯  ╰─────────────────────────────────╯
    ╭─── CONTROLLERS ─────────╮  ╭─[Manual Command]─[PID Gains]───╮
    │ esc  ⬤ en:y det:y       │  │  SURGE  SWAY  HEAVE  ROLL ...  │
    │ arm  ◉ en:y det:n       │  │  [inputs] × 9                  │
    │ imu  ○ en:n det:n       │  │  [Send]  [Zero all]            │
    │ ...                     │  ╰─────────────────────────────────╯
    ╰─────────────────────────╯
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ⬤ DB ONLINE  ○ REAL    AUV CONTROL · v0.1    last cmd → 14:22:01

Run with:  python ui.py
"""  # noqa: RUF002

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

# ─────────────────────────────────────────────────────────────────────────────
# External interface imports (with inert fallback stubs)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from libs.process_manager import ProcessManager  # type: ignore
except ImportError:
    class ProcessManager:  # type: ignore[no-redef]
        """Stub — replace with libs.process_manager.ProcessManager."""
        def start(self, name: str, **_: Any) -> None: ...
        def stop(self, name: str) -> None: ...
        def start_all(self) -> None: ...
        def stop_all(self) -> None: ...
        def status(self) -> dict[str, dict]:
            return {n: {"running": False, "pid": None} for n in SERVICES}

try:
    from libs.hardware_interface.process_manager import (  # type: ignore
        HardwareProcessManager,
    )
except ImportError:
    class HardwareProcessManager:  # type: ignore[no-redef]
        """Stub — replace with libs.hardware_interface.process_manager."""
        def start(self, name: str) -> None: ...
        def stop(self, name: str) -> None: ...
        def status(self) -> dict[str, dict]:
            return {
                name: {"enabled": False, "detected": False,
                       "running": False, "pid": None}
                for name in CONTROLLERS
            }

try:
    from libs.quick_request import AUVClient  # type: ignore
except ImportError:
    class AUVClient:  # type: ignore[no-redef]
        """Stub — replace with libs.quick_request.AUVClient."""
        def latest(self, table: str) -> dict | None: return None
        def post(self, table: str, **fields: Any) -> None: ...


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
SERVICES: tuple[str, ...] = ("db", "hardware_interface", "movement", "camera", "ai")
CONTROLLERS: tuple[str, ...] = (
    "esc", "arm", "imu", "psa", "torpedo", "pressure", "display",
)
INPUT_FIELDS: tuple[str, ...] = (
    "SURGE", "SWAY", "HEAVE", "ROLL", "PITCH", "YAW", "S1", "S2", "S3",
)
TELEMETRY_TABLES: tuple[str, ...] = ("imu", "depth", "power_safety")

POLL_INTERVAL: float = 0.5
STALE_AFTER: float   = 2.0
HISTORY: int         = 60

# Status dot glyphs
DOT_ON      = "⬤"
DOT_PARTIAL = "◉"
DOT_OFF     = "○"
DOT_BLINK   = "◎"   # alternated with DOT_ON for running services


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class TelemetrySeries:
    """Ring buffer of recent samples for a single channel."""
    samples: Deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY))
    last_update: float = 0.0

    def push(self, v: float | None) -> None:
        if v is None:
            return
        try:
            self.samples.append(float(v))
            self.last_update = time.monotonic()
        except (TypeError, ValueError):
            pass

    def is_stale(self, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        return self.last_update == 0.0 or (now - self.last_update) > STALE_AFTER

    def latest(self) -> float | None:
        return self.samples[-1] if self.samples else None


# ─────────────────────────────────────────────────────────────────────────────
# Panel widgets
# ─────────────────────────────────────────────────────────────────────────────
class PanelTitle(Static):
    """Accent-coloured section header rendered at the top of each panel."""


class ServicesPanel(Vertical):
    """Top-left — ProcessManager status with per-service start/stop toggles."""

    DEFAULT_CSS = """
    ServicesPanel { height: 1fr; }
    ServicesPanel .row {
        height: 3; padding: 0 1; layout: horizontal;
        border-bottom: dashed #30363d;
    }
    ServicesPanel .row.last { border-bottom: none; }
    ServicesPanel .name { width: 1fr; content-align: left middle; color: #e6edf3; }
    ServicesPanel .pid  { width: 10;  content-align: left middle; color: #8b949e; }
    ServicesPanel .dot  { width: 3;   content-align: center middle; }
    ServicesPanel Button { min-width: 7; height: 1; margin-left: 1; }
    ServicesPanel .dot-on      { color: #3fb950; }
    ServicesPanel .dot-off     { color: #8b949e; }
    ServicesPanel .hint { color: #8b949e; padding: 0 1 1 1; }
    """

    service_state: reactive[dict[str, dict]] = reactive(dict, recompose=False)
    _blink_state: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield PanelTitle("  SERVICES")
        for i, name in enumerate(SERVICES):
            classes = "row" + (" last" if i == len(SERVICES) - 1 else "")
            with Horizontal(classes=classes, id=f"svc-row-{name}"):
                yield Static(DOT_OFF, classes="dot dot-off", id=f"svc-dot-{name}")
                yield Static(name, classes="name")
                yield Static("pid —", classes="pid", id=f"svc-pid-{name}")
                yield Button("start", id=f"svc-toggle-{name}", variant="success")
        yield Static(
            "[1] db  [2] hw  [3] move  [4] cam  [5] ai  [a] all  [A] stop all",
            classes="hint",
        )

    def on_mount(self) -> None:
        self.set_interval(0.8, self._tick_blink)

    def _tick_blink(self) -> None:
        self._blink_state = not self._blink_state
        self._repaint_dots()

    def watch_service_state(self, state: dict[str, dict]) -> None:
        self._repaint_dots(state)

    def _repaint_dots(self, state: dict[str, dict] | None = None) -> None:
        state = state if state is not None else self.service_state
        for name in SERVICES:
            info    = state.get(name, {"running": False, "pid": None})
            running = bool(info.get("running"))
            pid     = info.get("pid")

            dot = self.query_one(f"#svc-dot-{name}", Static)
            if running:
                dot.update(DOT_BLINK if self._blink_state else DOT_ON)
                dot.set_classes("dot dot-on")
            else:
                dot.update(DOT_OFF)
                dot.set_classes("dot dot-off")

            self.query_one(f"#svc-pid-{name}", Static).update(
                f"pid {pid}" if pid else "pid —"
            )
            btn = self.query_one(f"#svc-toggle-{name}", Button)
            btn.label   = "stop"  if running else "start"
            btn.variant = "error" if running else "success"


class ControllersPanel(VerticalScroll):
    """Bottom-left — HardwareProcessManager status per controller."""

    DEFAULT_CSS = """
    ControllersPanel { height: 1fr; }
    ControllersPanel .row {
        height: 3; padding: 0 1; layout: horizontal;
        border-bottom: dashed #30363d;
    }
    ControllersPanel .row.last { border-bottom: none; }
    ControllersPanel .dot  { width: 3;  content-align: center middle; }
    ControllersPanel .name { width: 10; content-align: left middle; color: #e6edf3; }
    ControllersPanel .flag { width: 14; content-align: left middle; color: #8b949e; }
    ControllersPanel Button { min-width: 7; height: 1; margin-left: 1; }
    ControllersPanel .dot-on      { color: #3fb950; }
    ControllersPanel .dot-partial { color: #d29922; }
    ControllersPanel .dot-off     { color: #8b949e; }
    """

    controller_state: reactive[dict[str, dict]] = reactive(dict, recompose=False)

    def compose(self) -> ComposeResult:
        yield PanelTitle("  CONTROLLERS")
        for i, name in enumerate(CONTROLLERS):
            row_cls = "row" + (" last" if i == len(CONTROLLERS) - 1 else "")
            with Horizontal(classes=row_cls):
                yield Static(DOT_OFF, classes="dot dot-off", id=f"ctrl-dot-{name}")
                yield Static(name, classes="name")
                yield Static("en:— det:—", classes="flag", id=f"ctrl-flag-{name}")
                yield Button("start", id=f"ctrl-toggle-{name}", variant="success")

    def watch_controller_state(self, state: dict[str, dict]) -> None:
        for name in CONTROLLERS:
            info     = state.get(name, {})
            enabled  = bool(info.get("enabled"))
            detected = bool(info.get("detected"))
            running  = bool(info.get("running"))

            dot = self.query_one(f"#ctrl-dot-{name}", Static)
            if running:
                dot.update(DOT_ON)
                dot.set_classes("dot dot-on")
            elif enabled and not detected:
                dot.update(DOT_PARTIAL)
                dot.set_classes("dot dot-partial")
            else:
                dot.update(DOT_OFF)
                dot.set_classes("dot dot-off")

            self.query_one(f"#ctrl-flag-{name}", Static).update(
                f"en:{'y' if enabled else 'n'} det:{'y' if detected else 'n'}"
            )
            btn = self.query_one(f"#ctrl-toggle-{name}", Button)
            btn.label   = "stop"  if running else "start"
            btn.variant = "error" if running else "success"


class TimeSeriesPlot(Static):
    """A single plotext line-graph widget for one group of channels."""

    DEFAULT_CSS = """
    TimeSeriesPlot { height: 7; margin: 0 0 1 0; }
    """

    def __init__(
        self,
        title: str,
        channels: list[tuple[str, str]],
        unit: str = "",
    ) -> None:
        super().__init__()
        self._title    = title
        self._channels = channels
        self._unit     = unit
        self._data: dict[str, list[float]] = {k: [] for k, _ in channels}

    def update_series(self, key: str, samples: list[float]) -> None:
        if key in self._data:
            self._data[key] = samples

    def redraw(self) -> None:
        import plotext as plt
        from rich.text import Text

        w = max(self.size.width - 2, 20)
        h = max(self.size.height - 2, 4)

        plt.clf()
        plt.theme("dark")
        plt.plotsize(w, h)

        has_data    = False
        all_values: list[float] = []
        value_labels: list[str] = []

        for key, label in self._channels:
            data = self._data[key]
            if data:
                has_data = True
                all_values.extend(data)
                plt.plot(data, marker="braille")
                value_labels.append(f"{label}: {data[-1]:+.3f}")

        suffix = "    " + "  ".join(value_labels) if value_labels else ""
        plt.title(self._title + suffix)

        if all_values:
            lo, hi = min(all_values), max(all_values)
            if abs(hi - lo) > 1e-9:
                plt.yticks([lo, hi], [f"{lo:.2f}", f"{hi:.2f}"])

        plt.xfrequency(0)

        if has_data:
            self.update(Text.from_ansi(plt.build()))
        else:
            self.update(f"  [dim]{self._title} — waiting for data…[/dim]")


class TelemetryPanel(VerticalScroll):
    """Top-right — scrollable pane of grouped time-series plots."""

    DEFAULT_CSS = """
    TelemetryPanel { height: 1fr; }
    """

    PLOTS: tuple[tuple[str, list[tuple[str, str]], str], ...] = (
        ("Accelerometer", [("imu.ax", "x"), ("imu.ay", "y"), ("imu.az", "z")], "m/s²"),
        ("Gyroscope",     [("imu.gx", "x"), ("imu.gy", "y"), ("imu.gz", "z")], "rad/s"),
        ("Magnetometer",  [("imu.mx", "x"), ("imu.my", "y"), ("imu.mz", "z")], "µT"),
        ("Depth",         [("depth.m", "depth")], "m"),
        ("Power",         [("psa.v", "V"), ("psa.i", "A"), ("psa.t", "°C")], ""),
    )

    ALL_KEYS: tuple[str, ...] = tuple(
        key for _, channels, _ in PLOTS for key, _ in channels
    )

    telemetry: reactive[dict[str, TelemetrySeries]] = reactive(
        dict, recompose=False, always_update=True
    )

    def compose(self) -> ComposeResult:
        yield PanelTitle("  TELEMETRY")
        for title, channels, unit in self.PLOTS:
            yield TimeSeriesPlot(title=title, channels=channels, unit=unit)

    def watch_telemetry(self, telemetry: dict[str, TelemetrySeries]) -> None:
        for plot in self.query(TimeSeriesPlot):
            for key, _ in plot._channels:
                series = telemetry.get(key)
                if series:
                    plot.update_series(key, list(series.samples))
            plot.redraw()


class ManualCommandPanel(VerticalScroll):
    """Bottom-right tab — numeric inputs posted as an `inputs` row."""

    DEFAULT_CSS = """
    ManualCommandPanel { height: 1fr; }
    ManualCommandPanel .grid {
        layout: grid; grid-size: 3 3; grid-gutter: 1;
        padding: 1; height: auto;
    }
    ManualCommandPanel .field { layout: vertical; height: 5; }
    ManualCommandPanel .field Label { color: #8b949e; }
    ManualCommandPanel Input { height: 3; }
    ManualCommandPanel Input:focus { border: tall #58a6ff; }
    ManualCommandPanel .actions {
        layout: horizontal; padding: 1; height: 5;
    }
    ManualCommandPanel .actions Button { margin-right: 1; }
    ManualCommandPanel .ack { color: #3fb950; padding: 0 1; height: 1; content-align: left middle; }
    """

    last_ack: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield PanelTitle("  MANUAL COMMAND  ›  inputs")
        with Vertical(classes="grid"):
            for name in INPUT_FIELDS:
                with Vertical(classes="field"):
                    yield Label(name)
                    yield Input(placeholder="0", id=f"cmd-{name}",
                                value="0", type="number")
        with Horizontal(classes="actions"):
            yield Button("Send", id="cmd-send", variant="primary")
            yield Button("Zero all", id="cmd-zero")
            yield Static("", id="cmd-ack", classes="ack")

    def collect(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for name in INPUT_FIELDS:
            raw = self.query_one(f"#cmd-{name}", Input).value.strip()
            try:
                out[name] = float(raw) if raw else 0.0
            except ValueError:
                out[name] = 0.0
        return out

    def zero(self) -> None:
        for name in INPUT_FIELDS:
            self.query_one(f"#cmd-{name}", Input).value = "0"

    def watch_last_ack(self, ack: str) -> None:
        self.query_one("#cmd-ack", Static).update(ack)


class PIDTuningPanel(VerticalScroll):
    """Bottom-right tab — PID gain editor."""

    DEFAULT_CSS = """
    PIDTuningPanel { height: 1fr; }
    PIDTuningPanel .grid {
        layout: grid; grid-size: 3 2; grid-gutter: 1;
        padding: 1; height: auto;
    }
    PIDTuningPanel .field { layout: vertical; height: 5; }
    PIDTuningPanel .field Label { color: #8b949e; }
    PIDTuningPanel Input { height: 3; }
    PIDTuningPanel Input:focus { border: tall #58a6ff; }
    PIDTuningPanel .actions {
        layout: horizontal; padding: 1; height: 5;
    }
    PIDTuningPanel .actions Button { margin-right: 1; }
    PIDTuningPanel .ack { color: #3fb950; padding: 0 1; height: 1; content-align: left middle; }
    """

    _FIELDS: tuple[tuple[str, str], ...] = (
        ("ROLL_KP",  "Roll Kp"),
        ("ROLL_KI",  "Roll Ki"),
        ("ROLL_KD",  "Roll Kd"),
        ("PITCH_KP", "Pitch Kp"),
        ("PITCH_KI", "Pitch Ki"),
        ("PITCH_KD", "Pitch Kd"),
    )

    last_ack: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield PanelTitle("  PID GAINS  ›  roll / pitch stabilisation")
        with Vertical(classes="grid"):
            for key, label in self._FIELDS:
                with Vertical(classes="field"):
                    yield Label(label)
                    yield Input(placeholder="0.0", id=f"pid-{key}",
                                value="0.0", type="number")
        with Horizontal(classes="actions"):
            yield Button("Update", id="pid-update", variant="primary")
            yield Static("", id="pid-ack", classes="ack")

    def collect(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, _ in self._FIELDS:
            raw = self.query_one(f"#pid-{key}", Input).value.strip()
            try:
                out[key] = float(raw) if raw else 0.0
            except ValueError:
                out[key] = 0.0
        return out

    def watch_last_ack(self, ack: str) -> None:
        self.query_one("#pid-ack", Static).update(ack)


# ─────────────────────────────────────────────────────────────────────────────
# Status bar
# ─────────────────────────────────────────────────────────────────────────────
class StatusBar(Static):
    """Single-line bar docked at the bottom showing DB + sim state."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom; height: 1; padding: 0 1;
        background: #161b22; color: #8b949e;
    }
    StatusBar.online  { color: #3fb950; }
    StatusBar.offline { color: #f85149; }
    """

    db_online: reactive[bool] = reactive(False)
    last_post: reactive[str]  = reactive("")

    def watch_db_online(self, online: bool) -> None:
        self.set_class(online, "online")
        self.set_class(not online, "offline")
        self._refresh_content()

    def watch_last_post(self, _ack: str) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        db_dot   = DOT_ON if self.db_online else DOT_OFF
        db_label = "DB ONLINE" if self.db_online else "DB OFFLINE"
        try:
            sim = getattr(self.app, "simulation_mode", False)
        except Exception:
            sim = False
        mode = "◈ SIM" if sim else "○ REAL"
        tail = f"    {self.last_post}" if self.last_post else ""
        self.update(f"{db_dot} {db_label}    {mode}    AUV CONTROL · v0.1{tail}")


# ─────────────────────────────────────────────────────────────────────────────
# Log viewer modal
# ─────────────────────────────────────────────────────────────────────────────
class LogScreen(ModalScreen):
    """Full-screen modal tailing the AUV log file. Esc or L to close."""

    BINDINGS = [("escape", "dismiss", "Close"), ("l", "dismiss", "Close")]

    DEFAULT_CSS = """
    LogScreen { align: center middle; }
    LogScreen > Vertical {
        width: 96%; height: 92%;
        border: round #58a6ff;
        background: #161b22;
    }
    LogScreen #log-content {
        padding: 0 1; color: #e6edf3;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield PanelTitle("  PROCESS LOGS  ·  Esc to close  ·  auto-refresh 2 s")
            yield VerticalScroll(Static(id="log-content"), id="log-scroll")

    def on_mount(self) -> None:
        self._refresh_log()
        self.set_interval(2.0, self._refresh_log)

    def _refresh_log(self) -> None:
        from libs.logging_config import current_log_path

        log_path = current_log_path()
        try:
            lines   = log_path.read_text(encoding="utf-8").splitlines()
            content = "\n".join(lines[-300:]) or "(no log entries yet)"
        except FileNotFoundError:
            content = f"(log file not found: {log_path})\nStart some processes first."
        self.query_one("#log-content", Static).update(content)
        self.query_one("#log-scroll", VerticalScroll).scroll_end(animate=False)


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────
class AUVControlApp(App):
    """Main app — wires panels, owns poll workers and external interfaces."""

    CSS = """
    Screen { background: #0d1117; }

    #grid {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr 1fr;
        grid-rows: 1fr 1fr;
        grid-gutter: 1;
        padding: 1 1 0 1;
    }

    ServicesPanel, ControllersPanel, TelemetryPanel {
        border: round #30363d;
        background: #161b22;
        padding: 0 1;
    }

    #bottom-right {
        border: round #30363d;
        background: #161b22;
        padding: 0 1;
    }

    ServicesPanel:focus-within, ControllersPanel:focus-within,
    TelemetryPanel:focus-within, #bottom-right:focus-within {
        border: round #58a6ff;
    }

    PanelTitle {
        color: #58a6ff;
        text-style: bold;
        padding: 0 0 0 0;
        height: 1;
    }

    Header {
        background: #161b22;
        color: #58a6ff;
        text-style: bold;
    }

    Footer {
        background: #161b22;
        color: #8b949e;
    }

    TabbedContent ContentTab {
        color: #8b949e;
    }

    TabbedContent ContentTab.-active {
        color: #58a6ff;
        border-bottom: tall #58a6ff;
    }

    Button.-success { background: #1a3a1f; color: #3fb950; border: tall #3fb950; }
    Button.-error   { background: #3a1a1a; color: #f85149; border: tall #f85149; }
    Button.-primary { background: #1a2a3a; color: #58a6ff; border: tall #58a6ff; }
    Button.-default { background: #21262d; color: #e6edf3; border: tall #30363d; }

    .hint { color: #8b949e; padding: 0 0 1 0; }
    """

    BINDINGS = [
        Binding("q", "quit_safely", "Quit"),
        Binding("r", "refresh_all", "Refresh"),
        Binding("l", "show_logs", "Logs"),
        Binding("a", "start_all_services", "Start all"),
        Binding("A", "stop_all_services", "Stop all", show=False),
        Binding("1", "toggle_service('db')", "DB", show=False),
        Binding("2", "toggle_service('hardware_interface')", "HW", show=False),
        Binding("3", "toggle_service('movement')", "Movement", show=False),
        Binding("4", "toggle_service('camera')", "Camera", show=False),
        Binding("5", "toggle_service('ai')", "AI", show=False),
        Binding("s", "toggle_simulation_mode", "Sim mode"),
        Binding("z", "zero_inputs", "Zero inputs"),
        Binding("ctrl+s", "send_inputs", "Send"),
    ]

    simulation_mode: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self.pm     = ProcessManager()          # EXTERNAL: owned here
        self.hpm    = HardwareProcessManager()  # EXTERNAL: owned here
        self.client = AUVClient()               # EXTERNAL: owned here
        self._telemetry: dict[str, TelemetrySeries] = {
            key: TelemetrySeries() for key in TelemetryPanel.ALL_KEYS
        }

    # ── compose ──────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Grid(id="grid"):
            yield ServicesPanel(id="services")
            yield TelemetryPanel(id="telemetry")
            yield ControllersPanel(id="controllers")
            with TabbedContent(id="bottom-right"):
                with TabPane("Manual Command", id="tab-manual"):
                    yield ManualCommandPanel(id="manual")
                with TabPane("PID Gains", id="tab-pid"):
                    yield PIDTuningPanel(id="pid")
        yield StatusBar(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title     = "▸ AUV Control"
        self.sub_title = "autonomous underwater vehicle · ground station"
        self.action_refresh_all()
        self.set_interval(POLL_INTERVAL, self._poll_telemetry)
        self.set_interval(1.0, self._poll_processes)

    # ── pollers ──────────────────────────────────────────────────────────
    @work(exclusive=True, thread=True, group="telemetry")
    def _poll_telemetry(self) -> None:
        online = True
        for table in TELEMETRY_TABLES:
            try:
                row = self.client.latest(table)             # EXTERNAL: read
            except Exception:
                online = False
                row = None
            if not row:
                continue
            self._ingest_telemetry(table, row)

        self.query_one(TelemetryPanel).telemetry = dict(self._telemetry)
        self.query_one(StatusBar).db_online = online

    def _ingest_telemetry(self, table: str, row: dict) -> None:
        if table == "imu":
            mapping = {
                "ax": "ACCEL_X", "ay": "ACCEL_Y", "az": "ACCEL_Z",
                "gx": "GYRO_X",  "gy": "GYRO_Y",  "gz": "GYRO_Z",
                "mx": "MAG_X",   "my": "MAG_Y",   "mz": "MAG_Z",
            }
            for short, db_key in mapping.items():
                self._telemetry[f"imu.{short}"].push(row.get(db_key))
        elif table == "depth":
            self._telemetry["depth.m"].push(row.get("DEPTH"))
        elif table == "power_safety":
            self._telemetry["psa.v"].push(row.get("B1_VOLTAGE"))
            self._telemetry["psa.i"].push(row.get("B1_CURRENT"))
            self._telemetry["psa.t"].push(row.get("B1_TEMP"))

    def _poll_processes(self) -> None:
        try:
            svc = self.pm.status()                          # EXTERNAL: read
        except Exception:
            svc = {n: {"running": False, "pid": None} for n in SERVICES}
        try:
            ctrl = self.hpm.status()                        # EXTERNAL: read
        except Exception:
            ctrl = {n: {"enabled": False, "detected": False,
                        "running": False, "pid": None} for n in CONTROLLERS}
        self.query_one(ServicesPanel).service_state   = svc
        self.query_one(ControllersPanel).controller_state = ctrl

    # ── actions ──────────────────────────────────────────────────────────
    def watch_simulation_mode(self, sim: bool) -> None:
        label = "SIM" if sim else "REAL"
        self.notify(f"Mode: {label}", timeout=2)
        self.query_one(StatusBar)._refresh_content()

    def action_toggle_simulation_mode(self) -> None:
        self.simulation_mode = not self.simulation_mode

    def action_show_logs(self) -> None:
        self.push_screen(LogScreen())

    def action_refresh_all(self) -> None:
        self._poll_processes()
        self._poll_telemetry()

    def action_quit_safely(self) -> None:
        try:
            self.pm.stop_all()                              # EXTERNAL: write
        except Exception:
            pass
        self.exit()

    def action_start_all_services(self) -> None:
        try:
            self.pm.start_all()                             # EXTERNAL: write
        except Exception:
            pass
        self._poll_processes()

    def action_stop_all_services(self) -> None:
        try:
            self.pm.stop_all()                              # EXTERNAL: write
        except Exception:
            pass
        self._poll_processes()

    def action_toggle_service(self, name: str) -> None:
        self._toggle_service(name)

    def action_zero_inputs(self) -> None:
        self.query_one(ManualCommandPanel).zero()

    def action_send_inputs(self) -> None:
        self._send_inputs()

    # ── service / controller toggle ──────────────────────────────────────
    def _toggle_controller(self, name: str) -> None:
        info = self.query_one(ControllersPanel).controller_state.get(name, {})
        try:
            if info.get("running"):
                self.hpm.stop(name)                         # EXTERNAL: write
                self.notify(f"{name} stopped", timeout=2)
            else:
                self.hpm.start(name)                        # EXTERNAL: write
                self.notify(f"{name} starting…", timeout=2)
        except Exception as exc:
            self.notify(f"{name}: {exc}", severity="error")
        self._poll_processes()

    def _toggle_service(self, name: str) -> None:
        info = self.query_one(ServicesPanel).service_state.get(name, {})
        try:
            if info.get("running"):
                self.pm.stop(name)                          # EXTERNAL: write
                self.notify(f"{name} stopped", timeout=2)
            elif name == "hardware_interface":
                self.pm.start(name, simulation=self.simulation_mode)  # EXTERNAL: write
                self.notify(f"{name} starting…", timeout=2)
            else:
                self.pm.start(name)                         # EXTERNAL: write
                self.notify(f"{name} starting…", timeout=2)
        except Exception as exc:
            self.notify(f"{name}: {exc}", severity="error")
        self._poll_processes()

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("svc-toggle-"):
            self._toggle_service(bid.removeprefix("svc-toggle-"))
        elif bid.startswith("ctrl-toggle-"):
            self._toggle_controller(bid.removeprefix("ctrl-toggle-"))
        elif bid == "cmd-send":
            self._send_inputs()
        elif bid == "cmd-zero":
            self.query_one(ManualCommandPanel).zero()
        elif bid == "pid-update":
            self._send_pid_gains()

    # ── PID / manual send ────────────────────────────────────────────────
    def _send_pid_gains(self) -> None:
        panel  = self.query_one(PIDTuningPanel)
        fields = panel.collect()
        try:
            self.client.post("pid_gains", **fields)         # EXTERNAL: write
            panel.last_ack = f"updated · {time.strftime('%H:%M:%S')}"
        except Exception as exc:
            panel.last_ack = f"error: {exc}"
            self.notify(f"PID update failed: {exc}", severity="error")

    def _send_inputs(self) -> None:
        panel  = self.query_one(ManualCommandPanel)
        fields = panel.collect()
        try:
            self.client.post("inputs", **fields)            # EXTERNAL: write
            ts = time.strftime("%H:%M:%S")
            panel.last_ack = f"sent · {ts}"
            self.query_one(StatusBar).last_post = f"last cmd → inputs @ {ts}"
        except Exception as exc:
            panel.last_ack = f"error: {exc}"
            self.notify(f"send failed: {exc}", severity="error")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    AUVControlApp().run()


if __name__ == "__main__":
    main()
