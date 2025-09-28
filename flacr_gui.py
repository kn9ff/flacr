import configparser
import logging
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


WINDOW_WIDTH = 900
WINDOW_HEIGHT = 700
MIN_WIDTH = 700
MIN_HEIGHT = 600
LOG_DIR = Path.home() / ".flacr_logs"
LOG_FILE = LOG_DIR / "flacr_gui.log"
CONFIG_PATH = Path.home() / ".flacr_gui.ini"
ERROR_LOG_PATH = Path(__file__).parent / "flacr_error.log"
SCRIPT_PATH = Path(__file__).parent / "flacr.py"


def ensure_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            "kn9ff.flacr.gui"
        )
    except Exception:
        logging.getLogger("flacr_gui").debug(
            "Unable to set AppUserModelID", exc_info=True
        )


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if sys.stderr:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )

    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 10 * 1024 * 1024:
        backup = LOG_FILE.with_suffix(".log.old")
        try:
            if backup.exists():
                backup.unlink()
            LOG_FILE.replace(backup)
        except OSError:
            logging.getLogger("flacr_gui").warning("Unable to rotate log file")

    return logging.getLogger("flacr_gui")


logger = setup_logging()
ensure_app_user_model_id()


def format_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m {secs:02d}s"
    return f"{minutes:d}m {secs:02d}s"


@dataclass(slots=True)
class ProcessingOptions:
    directory: Optional[Path]
    encode_single: bool
    log_errors: bool
    thread_count: int
    show_progress: bool
    replay_gain: bool
    scan_only: bool
    test_only: bool
    quick_mode: bool
    sequential_mode: bool
    check_encoder: bool

    @classmethod
    def from_gui(cls, gui: "FlacrGUI") -> "ProcessingOptions":
        raw_dir = gui.dir_var.get().strip()
        directory = Path(raw_dir) if raw_dir else None
        return cls(
            directory=directory,
            encode_single=bool(gui.j_var.get()),
            log_errors=bool(gui.l_var.get()),
            thread_count=max(1, int(gui.m_var.get() or 1)),
            show_progress=bool(gui.p_var.get()),
            replay_gain=bool(gui.r_var.get()),
            scan_only=bool(gui.s_var.get()),
            test_only=bool(gui.t_var.get()),
            quick_mode=bool(gui.Q_var.get()),
            sequential_mode=bool(gui.S_var.get()),
            check_encoder=bool(gui.E_var.get()),
        )

    def validate(self) -> Tuple[bool, Optional[str]]:
        if self.directory is None:
            return False, "Please select a directory containing FLAC files."
        if not self.directory.exists():
            return False, f"Selected directory does not exist: {self.directory}"
        if not self.directory.is_dir():
            return False, "Selected path is not a directory."
        if self.thread_count < 1:
            return False, "Thread count must be at least 1."
        if platform.system() == "Windows":
            try:
                self.directory.resolve(strict=False)
            except OSError as exc:
                return False, f"Unable to access directory: {exc}"
        return True, None

    @property
    def requires_tqdm(self) -> bool:
        return self.show_progress or self.quick_mode or self.sequential_mode

    @property
    def requires_rsgain(self) -> bool:
        return self.replay_gain or self.quick_mode or self.sequential_mode

    def to_command(self) -> list[str]:
        command = [sys.executable, str(SCRIPT_PATH)]
        if self.directory:
            command += ["-d", str(self.directory)]
        if self.encode_single:
            command.append("-j")
        if self.log_errors:
            command.append("-l")
        if self.thread_count:
            command += ["-m", str(self.thread_count)]
        if self.show_progress:
            command.append("-p")
        if self.replay_gain:
            command.append("-r")
        if self.scan_only:
            command.append("-s")
        if self.test_only:
            command.append("-t")
        if self.quick_mode:
            command.append("-Q")
        if self.sequential_mode:
            command.append("-S")
        if self.check_encoder:
            command.append("-E")
        return command


class FlacrGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FLACR - FLAC Recompressor GUI")

        self.process: Optional[subprocess.Popen[str]] = None
        self.process_thread: Optional[threading.Thread] = None
        self.process_active = False
        self.output_queue: Optional[queue.Queue[tuple[str, object]]] = None
        self.max_log_lines = 2000
        self.start_time: Optional[float] = None
        self.files_processed = 0
        self.total_files = 0
        self._seen_files: set[str] = set()
        self._last_output_time: Optional[float] = None
        self._exit_code: Optional[int] = None
        self._queue_poll_job: Optional[str] = None
        self._runtime_job: Optional[str] = None
        self._cancel_requested = False
        self._pending_close = False
        self._tqdm_available: Optional[bool] = None

        self._setup_window()
        self._create_widgets()
        self._load_settings()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self._validate_environment)

    def _setup_window(self) -> None:
        icon_candidates = [
            Path(__file__).parent / "flaccheck.ico",
            Path(__file__).parent / "icon.ico",
            Path.cwd() / "flaccheck.ico",
            Path.cwd() / "icon.ico",
        ]
        for icon in icon_candidates:
            if icon.exists():
                try:
                    self.iconbitmap(str(icon))
                    break
                except Exception:
                    logger.debug("Unable to apply icon %s", icon, exc_info=True)

        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        try:
            self.update_idletasks()
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            x_pos = max(0, (screen_w - WINDOW_WIDTH) // 2)
            y_pos = max(0, (screen_h - WINDOW_HEIGHT) // 2)
            self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x_pos}+{y_pos}")
        except Exception:
            logger.debug("Unable to centre window", exc_info=True)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

    def _create_widgets(self) -> None:
        dir_frame = tk.Frame(self)
        dir_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        dir_frame.grid_columnconfigure(1, weight=1)

        tk.Label(dir_frame, text="Directory:").grid(row=0, column=0, sticky="w")
        self.dir_var = tk.StringVar(value=str(Path.cwd()))
        self.dir_entry = tk.Entry(dir_frame, textvariable=self.dir_var, width=50)
        self.dir_entry.grid(row=0, column=1, sticky="ew", padx=(5, 5))
        tk.Button(dir_frame, text="Browse...", command=self.browse_dir).grid(
            row=0, column=2, sticky="e"
        )

        self.options_frame = tk.LabelFrame(self, text="Options")
        self.options_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        for col in range(4):
            self.options_frame.grid_columnconfigure(col, weight=1)

        self.j_var = tk.BooleanVar()
        self.j_check = tk.Checkbutton(
            self.options_frame,
            text="Encode 1 file at a time with multi-threading (-j)",
            variable=self.j_var,
            command=self.update_option_states,
        )
        self.j_check.grid(row=0, column=0, sticky="w", padx=(5, 0), pady=2)

        self.l_var = tk.BooleanVar()
        self.l_check = tk.Checkbutton(
            self.options_frame, text="Log errors to flacr.log (-l)", variable=self.l_var
        )
        self.l_check.grid(row=0, column=1, sticky="w", padx=(5, 0), pady=2)

        self.m_var = tk.IntVar(value=max(1, os.cpu_count() or 1))
        tk.Label(self.options_frame, text="Thread count (-m):").grid(
            row=1, column=0, sticky="w", padx=(5, 0)
        )
        self.m_spin = tk.Spinbox(
            self.options_frame,
            from_=1,
            to=max(1, os.cpu_count() or 1),
            textvariable=self.m_var,
            width=6,
        )
        self.m_spin.grid(row=1, column=1, sticky="w", padx=(5, 0), pady=2)

        self.p_var = tk.BooleanVar()
        self.p_check = tk.Checkbutton(
            self.options_frame, text="Show progress bars (-p)", variable=self.p_var
        )
        self.p_check.grid(row=1, column=2, sticky="w", padx=(5, 0), pady=2)

        self.r_var = tk.BooleanVar()
        self.r_check = tk.Checkbutton(
            self.options_frame, text="Calculate replay gain (-r)", variable=self.r_var
        )
        self.r_check.grid(row=2, column=0, sticky="w", padx=(5, 0), pady=2)

        self.s_var = tk.BooleanVar()
        self.s_check = tk.Checkbutton(
            self.options_frame, text="Only scan current folder (-s)", variable=self.s_var
        )
        self.s_check.grid(row=2, column=1, sticky="w", padx=(5, 0), pady=2)

        self.t_var = tk.BooleanVar()
        self.t_check = tk.Checkbutton(
            self.options_frame, text="Test only, skip recompression (-t)", variable=self.t_var
        )
        self.t_check.grid(row=2, column=2, sticky="w", padx=(5, 0), pady=2)

        self.Q_var = tk.BooleanVar()
        self.Q_check = tk.Checkbutton(
            self.options_frame,
            text="Quick mode (-Q)",
            variable=self.Q_var,
            command=self.update_option_states,
        )
        self.Q_check.grid(row=3, column=0, sticky="w", padx=(5, 0), pady=2)

        self.S_var = tk.BooleanVar()
        self.S_check = tk.Checkbutton(
            self.options_frame,
            text="Sequential mode (-S)",
            variable=self.S_var,
            command=self.update_option_states,
        )
        self.S_check.grid(row=3, column=1, sticky="w", padx=(5, 0), pady=2)

        self.E_var = tk.BooleanVar()
        self.E_check = tk.Checkbutton(
            self.options_frame, text="Check ENCODER metadata (-E)", variable=self.E_var
        )
        self.E_check.grid(row=3, column=2, sticky="w", padx=(5, 0), pady=2)

        self.progress_frame = tk.Frame(self)
        self.progress_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

        self.progress_label = tk.Label(
            self.progress_frame,
            text="Ready",
            anchor="w",
            relief="sunken",
            padx=6,
        )
        self.progress_label.pack(fill="x", side="top")

        self.progress = ttk.Progressbar(
            self.progress_frame, orient="horizontal", mode="determinate"
        )
        self.progress.pack(fill="x", side="top", pady=(4, 0))

        self.runtime_var = tk.StringVar(value="Idle")
        self.runtime_label = tk.Label(
            self.progress_frame,
            textvariable=self.runtime_var,
            anchor="w",
            padx=6,
        )
        self.runtime_label.pack(fill="x", side="top", pady=(4, 0))

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5)
        btn_frame.grid_columnconfigure(4, weight=1)

        self.run_button = tk.Button(btn_frame, text="Run", command=self.run_flacr)
        self.run_button.grid(row=0, column=0, padx=(0, 5), sticky="w")

        self.cancel_button = tk.Button(
            btn_frame, text="Cancel", state="disabled", command=self.cancel_flacr
        )
        self.cancel_button.grid(row=0, column=1, padx=(0, 5), sticky="w")

        tk.Button(btn_frame, text="View Error Log", command=self.open_error_log).grid(
            row=0, column=2, padx=(0, 5), sticky="w"
        )
        tk.Button(btn_frame, text="Help", command=self.show_help).grid(
            row=0, column=3, padx=(0, 5), sticky="w"
        )
        tk.Button(btn_frame, text="Copy CLI Command", command=self.copy_cli_command).grid(
            row=0, column=4, sticky="e"
        )

        self.output_text = tk.Text(
            self, height=18, wrap="word", state="disabled", bg="#1e1e1e", fg="#dcdcdc"
        )
        self.output_text.grid(row=4, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.output_text.tag_configure("error", foreground="#ff6666")
        self.output_text.tag_configure("warn", foreground="#ffcc66")
        self.output_text.tag_configure("success", foreground="#90ee90")
        self.output_text.tag_configure("info", foreground="#add8e6")

    def _validate_environment(self) -> None:
        logger.info("Validating environment")
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state="disabled")

        details = [
            "FLACR GUI - Environment validation",
            "=" * 60,
            f"System: {platform.system()} {platform.release()}",
            f"Python: {sys.version.split()[0]} ({sys.executable})",
            f"Working directory: {Path.cwd()}",
            "",
        ]

        if SCRIPT_PATH.exists():
            details.append(f"flacr.py located at {SCRIPT_PATH}")
        else:
            details.append(f"flacr.py missing (expected at {SCRIPT_PATH})")

        for line in details:
            self.append_output(line + "\n", tag="info")

        if SCRIPT_PATH.exists():
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(SCRIPT_PATH)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    self.append_output("Syntax check: OK\n", tag="success")
                else:
                    self.append_output(
                        f"Syntax check failed: {result.stderr.strip()}\n", tag="error"
                    )
            except subprocess.SubprocessError as exc:
                self.append_output(f"Syntax check failed: {exc}\n", tag="warn")
        else:
            self.progress_label.config(text="flacr.py missing - update directory")

        self.progress_label.config(text="Ready - Select directory to begin")

    def browse_dir(self) -> None:
        initial_dir = self.dir_var.get()
        if not initial_dir or not Path(initial_dir).exists():
            initial_dir = str(Path.home())

        directory = filedialog.askdirectory(
            initialdir=initial_dir, title="Select directory containing FLAC files"
        )
        if not directory:
            return

        dir_path = Path(directory)
        if not dir_path.is_dir():
            messagebox.showerror("Invalid Directory", "Selected path is not a directory.")
            return

        self.dir_var.set(str(dir_path))
        logger.info("Directory set to %s", dir_path)

        try:
            flac_count = sum(1 for _ in dir_path.rglob("*.flac"))
        except OSError as exc:
            logger.warning("Unable to inspect directory %s", dir_path, exc_info=True)
            self.progress_label.config(text=f"Directory selected: {dir_path}")
            return

        if flac_count:
            self.progress_label.config(
                text=f"Directory selected - Found {flac_count} FLAC file(s)"
            )
        else:
            self.progress_label.config(text="Directory selected - No FLAC files found")

    def run_flacr(self) -> None:
        options = ProcessingOptions.from_gui(self)
        valid, message = options.validate()
        if not valid:
            messagebox.showerror("Invalid Configuration", message)
            return

        if not SCRIPT_PATH.exists():
            messagebox.showerror(
                "Script Missing",
                f"Cannot locate flacr.py at {SCRIPT_PATH}. Update the installation and retry.",
            )
            return

        if not self.check_dependencies(options):
            return

        if (options.encode_single or options.sequential_mode) and not self.flac_supports_threads():
            messagebox.showwarning(
                "FLAC Upgrade Recommended",
                "FLAC 1.5.0 or newer is required for -j / -S. Disable the option or upgrade FLAC.",
            )
            return

        if options.requires_tqdm and not self.tqdm_installed():
            if not messagebox.askyesno(
                "tqdm Not Installed",
                "Progress bars require the tqdm package. Continue without it?",
            ):
                return

        self.save_settings()
        self._prepare_for_run(options)
        command = options.to_command()
        self._start_process(command)

    def _prepare_for_run(self, options: ProcessingOptions) -> None:
        self.process_active = True
        self._cancel_requested = False
        self.files_processed = 0
        self.total_files = 0
        self._seen_files.clear()
        self._exit_code = None
        self.start_time = time.time()
        self._last_output_time = self.start_time

        self.output_queue = queue.Queue()
        self.progress_label.config(text="Initialising...")
        self.progress.configure(value=0, maximum=1)
        self.runtime_var.set("Elapsed: 0s")
        self._start_runtime_timer()
        self._set_buttons_running()

        self.output_text.config(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state="disabled")
        start_stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.append_output(f"Starting flacr.py at {start_stamp}\n", tag="info")
        self.append_output(
            "Command: " + " ".join(options.to_command()) + "\n", tag="info"
        )

    def _start_process(self, command: list[str]) -> None:
        working_dir = str(SCRIPT_PATH.parent)
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["PYTHONUNBUFFERED"] = "1"

        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        def worker() -> None:
            try:
                logger.info("Launching flacr.py with args: %s", command)
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=working_dir,
                    env=env,
                    creationflags=creationflags,
                    startupinfo=startupinfo,
                )
                assert self.process.stdout is not None
                for raw_line in self.process.stdout:
                    line = raw_line.rstrip("\r\n")
                    if self.output_queue:
                        self.output_queue.put(("line", line))
                exit_code = self.process.wait()
                if self.output_queue:
                    self.output_queue.put(("exit", exit_code))
            except Exception as exc:
                if self.output_queue:
                    self.output_queue.put(("error", str(exc)))
                logger.exception("Process worker failed")
            finally:
                self.process_active = False
                if self.output_queue:
                    self.output_queue.put(("sentinel", None))
                if self.process and self.process.stdout:
                    try:
                        self.process.stdout.close()
                    except Exception:
                        pass
                self.process = None

        self.process_thread = threading.Thread(
            target=worker, name="FlacrProcessWorker", daemon=True
        )
        self.process_thread.start()
        self._schedule_queue_poll()

    def _schedule_queue_poll(self) -> None:
        if self._queue_poll_job is None:
            self._queue_poll_job = self.after(150, self._queue_poll)

    def _queue_poll(self) -> None:
        self._queue_poll_job = None
        if not self.output_queue:
            return

        while True:
            try:
                event, payload = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if event == "line":
                self._handle_process_output_line(str(payload))
            elif event == "error":
                self.append_output(f"Error: {payload}\n", tag="error")
            elif event == "exit":
                self._exit_code = int(payload) if payload is not None else None
            elif event == "sentinel":
                # Sentinel consumed later when queue fully drained
                pass

        if self.process_active or (self.process_thread and self.process_thread.is_alive()):
            self._queue_poll_job = self.after(200, self._queue_poll)
            if self.process_active and self._last_output_time:
                idle_for = time.time() - self._last_output_time
                if idle_for > 60:
                    self.progress_label.config(
                        text=f"Waiting... no new output for {int(idle_for)}s"
                    )
            return

        if self.output_queue.empty():
            self._finalise_processing()
        else:
            self._queue_poll_job = self.after(200, self._queue_poll)

    def _handle_process_output_line(self, line: str) -> None:
        self._last_output_time = time.time()
        tag = self._categorise_tag(line)
        self.append_output(line + "\n", tag=tag)
        self._analyse_line_for_progress(line)

    def _categorise_tag(self, line: str) -> Optional[str]:
        lower = line.lower()
        if any(keyword in lower for keyword in ["error", "failed", "traceback"]):
            return "error"
        if any(keyword in lower for keyword in ["warning", "skipping", "retry"]):
            return "warn"
        if any(keyword in lower for keyword in ["success", "completed", "done"]):
            return "success"
        return None

    def _analyse_line_for_progress(self, line: str) -> None:
        total_match = re.search(r"found\s+(\d+)\s+flac", line, re.IGNORECASE)
        if total_match:
            self.total_files = int(total_match.group(1))
            self.progress.configure(maximum=max(1, self.total_files))
            self.progress_label.config(text=f"Found {self.total_files} FLAC file(s)")

        file_info = self._extract_file_info(line)
        if not file_info:
            return

        file_path, operation = file_info
        status_text = f"{operation.title()}: {file_path.name}"

        if operation in {"processing", "encoding", "verifying", "completed", "checking"}:
            if file_path.as_posix() not in self._seen_files:
                self._seen_files.add(file_path.as_posix())
                self.files_processed += 1

        total = self.total_files or max(1, self.files_processed)
        self.update_progress(self.files_processed, total, file_path, status_text)

    def _extract_file_info(self, line: str) -> Optional[Tuple[Path, str]]:
        patterns = [
            (r"Processing:\s*(.+\.flac)", "processing"),
            (r"Encoding:\s*(.+\.flac)", "encoding"),
            (r"Verifying:\s*(.+\.flac)", "verifying"),
            (r"Checking:\s*(.+\.flac)", "checking"),
            (r"Successfully processed:\s*(.+\.flac)", "completed"),
            (r"Skipping\s+(.+\.flac)", "skipped"),
            (r"Error processing\s+(.+\.flac)", "error"),
        ]
        for pattern, label in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                raw_path = match.group(1).strip().strip('"')
                return Path(raw_path), label
        return None

    def update_progress(
        self,
        processed: int,
        total: int,
        current_file: Optional[Path] = None,
        status_text: Optional[str] = None,
    ) -> None:
        total = max(1, total)
        processed = max(0, min(processed, total))
        self.progress.configure(maximum=total, value=processed)

        if status_text:
            label = status_text
        elif current_file:
            label = f"Processing {current_file.name} ({processed}/{total})"
        else:
            label = f"Progress: {processed}/{total}"

        pct = processed / total * 100
        label = f"{label} - {pct:.1f}%"
        self.progress_label.config(text=label)
        self._update_window_title(pct)

    def _update_window_title(self, percentage: float) -> None:
        clamped = max(0.0, min(percentage, 100.0))
        self.title(f"FLACR GUI - {clamped:.0f}% complete")

    def append_output(self, text: str, tag: Optional[str] = None) -> None:
        self.after_idle(self._append_output_safe, text, tag)

    def _append_output_safe(self, text: str, tag: Optional[str] = None) -> None:
        if not self.output_text.winfo_exists():
            return

        self.output_text.config(state="normal")
        self._ensure_log_size()
        self.output_text.insert(tk.END, text, tag)
        self.output_text.see(tk.END)
        self.output_text.config(state="disabled")

    def _ensure_log_size(self) -> None:
        current_lines = int(float(self.output_text.index("end-1c").split(".")[0]))
        if current_lines <= self.max_log_lines:
            return
        excess = current_lines - self.max_log_lines
        self.output_text.delete("1.0", f"{excess + 1}.0")

    def _start_runtime_timer(self) -> None:
        self._stop_runtime_timer()
        self._runtime_job = self.after(1000, self._update_runtime_label)

    def _update_runtime_label(self) -> None:
        if self.process_active and self.start_time:
            elapsed = int(time.time() - self.start_time)
            self.runtime_var.set(f"Elapsed: {format_duration(elapsed)}")
            self._runtime_job = self.after(1000, self._update_runtime_label)
        else:
            self.runtime_var.set("Idle")
            self._runtime_job = None

    def _stop_runtime_timer(self) -> None:
        if self._runtime_job is not None:
            try:
                self.after_cancel(self._runtime_job)
            except Exception:
                pass
            self._runtime_job = None

    def cancel_flacr(self) -> None:
        if not self.process_active:
            return
        self._cancel_requested = True
        self.append_output("\nCancellation requested by user.\n", tag="warn")
        self.progress_label.config(text="Cancelling...")
        self._terminate_process()

    def _terminate_process(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        try:
            self.process.terminate()
            wait_until = time.time() + 5
            while time.time() < wait_until and self.process.poll() is None:
                time.sleep(0.1)
            if self.process.poll() is None:
                self.process.kill()
        except Exception:
            logger.exception("Unable to terminate process")

    def _finalise_processing(self) -> None:
        self.process_active = False
        self._stop_runtime_timer()
        self._set_buttons_idle()
        elapsed = (
            format_duration(int(time.time() - self.start_time)) if self.start_time else "0s"
        )
        self.runtime_var.set(f"Elapsed: {elapsed}")

        if self._cancel_requested:
            message = f"Processing cancelled after {elapsed}. Processed {self.files_processed} file(s)."
            self.append_output("\nProcessing cancelled by user.\n", tag="warn")
            messagebox.showinfo("Cancelled", message)
        elif self._exit_code in (0, None):
            total = max(self.files_processed, self.total_files)
            message = (
                f"Processing completed successfully in {elapsed}. "
                f"Processed {self.files_processed} of {total} file(s)."
            )
            self.append_output("\nProcessing completed successfully.\n", tag="success")
            messagebox.showinfo("Success", message)
        else:
            message = (
                f"Processing failed with exit code {self._exit_code} after {elapsed}. "
                "Review the log for details."
            )
            self.append_output(
                f"\nProcessing failed with exit code {self._exit_code}.\n", tag="error"
            )
            messagebox.showerror("Error", message)

        self._cleanup_after_run()
        if self._pending_close:
            self.after(150, self._close_window)

    def _cleanup_after_run(self) -> None:
        self.process_thread = None
        self.process = None
        self.output_queue = None
        self._queue_poll_job = None
        self.title("FLACR - FLAC Recompressor GUI")
        self.progress_label.config(text="Ready")

    def _set_buttons_running(self) -> None:
        self.run_button.config(state="disabled")
        self.cancel_button.config(state="normal")

    def _set_buttons_idle(self) -> None:
        self.run_button.config(state="normal")
        self.cancel_button.config(state="disabled")

    def check_dependencies(self, options: ProcessingOptions) -> bool:
        missing = []
        for tool in ("flac", "metaflac"):
            if shutil.which(tool) is None:
                missing.append(tool)
        if options.requires_rsgain and shutil.which("rsgain") is None:
            missing.append("rsgain")

        if missing:
            messagebox.showerror(
                "Missing Dependencies",
                "The following tools are required but not available: "
                + ", ".join(missing),
            )
            return False
        return True

    def flac_supports_threads(self) -> bool:
        flac_path = shutil.which("flac")
        if not flac_path:
            return False
        try:
            result = subprocess.run(
                [flac_path, "--version"], capture_output=True, text=True, timeout=5
            )
        except (subprocess.SubprocessError, OSError):
            return False
        output = result.stdout or result.stderr or ""
        match = re.search(r"flac\s+(\d+)\.(\d+)\.(\d+)", output)
        if not match:
            return False
        major, minor, patch = map(int, match.groups())
        return (major, minor, patch) >= (1, 5, 0)

    def tqdm_installed(self) -> bool:
        if self._tqdm_available is not None:
            return self._tqdm_available
        try:
            import importlib.util

            spec = importlib.util.find_spec("tqdm")
            if spec is not None:
                self._tqdm_available = True
                return True
        except Exception:
            logger.debug("tqdm detection via find_spec failed", exc_info=True)
        try:
            import tqdm  # type: ignore

            self._tqdm_available = True
            return True
        except ModuleNotFoundError:
            self._tqdm_available = False
            return False
        except Exception:
            logger.debug("Unexpected error importing tqdm", exc_info=True)
            self._tqdm_available = False
            return False

    def open_error_log(self) -> None:
        if not ERROR_LOG_PATH.exists():
            messagebox.showinfo("Error Log", "No error log found.")
            return
        log_window = tk.Toplevel(self)
        log_window.title("flacr_error.log")
        log_window.geometry("700x420")
        text_widget = tk.Text(log_window, wrap="word")
        text_widget.pack(expand=True, fill="both")
        try:
            content = ERROR_LOG_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            content = f"Unable to read log file: {exc}"
        text_widget.insert("1.0", content)
        text_widget.config(state="disabled")

    def show_help(self) -> None:
        help_text = (
            "flacr - FLAC Recompressor GUI\n\n"
            "-d  Directory to scan for .flac files\n"
            "-j  Encode one file at a time with multi-threading (flac >= 1.5.0)\n"
            "-l  Log errors to flacr.log\n"
            "-m  Number of threads (conversion and replay gain)\n"
            "-p  Show progress bars (requires tqdm)\n"
            "-r  Calculate replay gain (requires rsgain)\n"
            "-s  Only scan the current folder\n"
            "-t  Test only, skip recompression\n"
            "-Q  Quick mode (-r -p -m all available threads)\n"
            "-S  Sequential mode (-j -r -p -m 4)\n"
            "-E  Check and fix ENCODER metadata tags\n"
        )
        messagebox.showinfo("Help", help_text)

    def copy_cli_command(self) -> None:
        options = ProcessingOptions.from_gui(self)
        command = options.to_command()
        if not command:
            messagebox.showwarning("No Command", "Unable to build CLI command.")
            return
        try:
            cmdline = subprocess.list2cmdline(command)
        except Exception:
            cmdline = " ".join(command)
        self.clipboard_clear()
        self.clipboard_append(cmdline)
        messagebox.showinfo("CLI Command", f"Copied to clipboard:\n{cmdline}")

    def update_option_states(self) -> None:
        if self.Q_var.get():
            self.S_var.set(False)
            self.r_var.set(True)
            self.p_var.set(True)
            self.m_var.set(max(1, os.cpu_count() or 1))
            self.m_spin.config(state="disabled")
            self.r_check.config(state="disabled")
            self.p_check.config(state="disabled")
            self.S_check.config(state="disabled")
        else:
            self.m_spin.config(state="normal")
            self.r_check.config(state="normal")
            self.p_check.config(state="normal")
            self.S_check.config(state="normal")

        if self.S_var.get():
            self.Q_var.set(False)
            self.r_var.set(True)
            self.p_var.set(True)
            self.j_var.set(True)
            default_threads = 4 if (os.cpu_count() or 1) >= 4 else max(1, os.cpu_count() or 1)
            self.m_var.set(default_threads)
            self.m_spin.config(state="disabled")
            self.r_check.config(state="disabled")
            self.p_check.config(state="disabled")
            self.j_check.config(state="disabled")
            self.Q_check.config(state="disabled")
        else:
            self.j_check.config(state="normal")
            self.Q_check.config(state="normal")
            if not self.Q_var.get():
                self.m_spin.config(state="normal")
                self.r_check.config(state="normal")
                self.p_check.config(state="normal")

    def save_settings(self) -> None:
        config = configparser.ConfigParser()
        config.add_section("main")
        config.set("main", "directory", self.dir_var.get())
        config.set("main", "j", str(self.j_var.get()))
        config.set("main", "l", str(self.l_var.get()))
        config.set("main", "m", str(self.m_var.get()))
        config.set("main", "p", str(self.p_var.get()))
        config.set("main", "r", str(self.r_var.get()))
        config.set("main", "s", str(self.s_var.get()))
        config.set("main", "t", str(self.t_var.get()))
        config.set("main", "Q", str(self.Q_var.get()))
        config.set("main", "S", str(self.S_var.get()))
        config.set("main", "E", str(self.E_var.get()))
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with CONFIG_PATH.open("w", encoding="utf-8") as handle:
                config.write(handle)
        except OSError:
            logger.exception("Unable to save configuration")

    def _load_settings(self) -> None:
        config = configparser.ConfigParser()
        if not CONFIG_PATH.exists():
            return
        try:
            config.read(CONFIG_PATH, encoding="utf-8")
        except (OSError, configparser.Error):
            logger.warning("Unable to read configuration", exc_info=True)
            return
        if not config.has_section("main"):
            return
        section = config["main"]
        self.dir_var.set(section.get("directory", self.dir_var.get()))
        self.j_var.set(section.getboolean("j", fallback=False))
        self.l_var.set(section.getboolean("l", fallback=False))
        self.m_var.set(section.getint("m", fallback=max(1, os.cpu_count() or 1)))
        self.p_var.set(section.getboolean("p", fallback=False))
        self.r_var.set(section.getboolean("r", fallback=False))
        self.s_var.set(section.getboolean("s", fallback=False))
        self.t_var.set(section.getboolean("t", fallback=False))
        self.Q_var.set(section.getboolean("Q", fallback=False))
        self.S_var.set(section.getboolean("S", fallback=False))
        self.E_var.set(section.getboolean("E", fallback=False))
        self.update_option_states()

    def on_close(self) -> None:
        if self.process_active:
            if not messagebox.askyesno(
                "Process Running",
                "A FLAC job is in progress. Cancel and exit?",
                icon="warning",
            ):
                return
            self._pending_close = True
            self.cancel_flacr()
            return
        self.save_settings()
        self._close_window()

    def _close_window(self) -> None:
        self._cancel_after_jobs()
        self.destroy()

    def _cancel_after_jobs(self) -> None:
        if self._queue_poll_job is not None:
            try:
                self.after_cancel(self._queue_poll_job)
            except Exception:
                pass
            self._queue_poll_job = None
        self._stop_runtime_timer()


if __name__ == "__main__":
    app = FlacrGUI()
    app.mainloop()
