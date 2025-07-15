# --- Improved GUI for flacr.py ---
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import subprocess
import signal
import sys
import os
import shutil
import configparser
import re
import time
import queue
import logging
import traceback
import platform
from pathlib import Path
from io import StringIO

# Import fcntl for Unix systems only
try:
    import fcntl

    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False


# Setup logging
def setup_logging():
    """Setup logging for the GUI application"""
    log_dir = Path.home() / ".flacr_logs"
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / "flacr_gui.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Rotate log files if they get too large
    if log_file.exists() and log_file.stat().st_size > 10 * 1024 * 1024:  # 10MB
        backup_file = log_dir / "flacr_gui.log.old"
        if backup_file.exists():
            backup_file.unlink()
        log_file.rename(backup_file)

    return logging.getLogger("flacr_gui")


logger = setup_logging()

# Use pathlib for better file handling
SCRIPT_PATH = Path(__file__).parent / "flacr.py"
CONFIG_PATH = Path.home() / ".flacr_gui.ini"
ERROR_LOG_PATH = Path(__file__).parent / "flacr_error.log"


class FlacrGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FLACR - FLAC Recompressor GUI")

        # Initialize state variables with comprehensive tracking
        self.process = None
        self.process_active = False
        self.max_log_lines = 2000  # Increased for better logging
        self.output_queue = None
        self.start_time = None
        self.files_processed = 0
        self.total_files = None
        self._last_display_update = time.time()
        self._completion_handled = False

        logger.info("Initializing FLAC GUI")

        # Setup GUI with error handling
        try:
            self._setup_window()
            self.create_widgets()
            self.load_settings()
            self.protocol("WM_DELETE_WINDOW", self.on_close)

            # Validate environment after GUI setup
            self.after(100, self._validate_environment)

        except Exception as e:
            logger.error(f"Error during GUI initialization: {e}")
            logger.error(traceback.format_exc())
            messagebox.showerror(
                "Initialization Error", f"Failed to initialize GUI: {e}"
            )

        logger.info("FLAC GUI initialized successfully")

    def _setup_window(self):
        """Setup window properties with comprehensive configuration"""
        try:
            # Set application icon if available
            icon_paths = [
                Path(__file__).parent / "flaccheck.ico",
                Path(__file__).parent / "icon.ico",
                Path.cwd() / "flaccheck.ico",
                Path.cwd() / "icon.ico",
            ]

            for icon_path in icon_paths:
                if icon_path.exists():
                    try:
                        self.iconbitmap(str(icon_path))
                        logger.info(f"Set application icon: {icon_path}")
                        break
                    except Exception as e:
                        logger.warning(f"Could not set icon {icon_path}: {e}")
            else:
                logger.info("No application icon found, using default")

        except Exception as e:
            logger.warning(f"Error setting up application icon: {e}")

        # Window size and position
        try:
            self.geometry("900x700")  # Larger window for better usability
            self.minsize(700, 600)  # Minimum usable size

            # Center window on screen with error handling
            try:
                self.update_idletasks()
                screen_width = self.winfo_screenwidth()
                screen_height = self.winfo_screenheight()
                window_width = 900
                window_height = 700

                x = max(0, (screen_width - window_width) // 2)
                y = max(0, (screen_height - window_height) // 2)

                self.geometry(f"{window_width}x{window_height}+{x}+{y}")
                logger.info(f"Window positioned at {x}x{y}")

            except Exception as e:
                logger.warning(f"Could not center window: {e}")
                # Fallback to default positioning
                self.geometry("900x700+100+100")

        except Exception as e:
            logger.error(f"Error setting up window geometry: {e}")
            # Minimal fallback
            try:
                self.geometry("800x600")
            except:
                pass  # Use whatever default tkinter provides

    def _validate_environment(self):
        """Comprehensive environment validation with user feedback"""
        try:
            logger.info("Starting environment validation")

            # Clear any existing output and show validation status
            if hasattr(self, "output_text"):
                self.output_text.config(state="normal")
                self.output_text.delete("1.0", tk.END)
                self.output_text.config(state="disabled")

            self.append_output("🔧 FLACR GUI - Environment Validation\n", tag="info")
            self.append_output("=" * 60 + "\n", tag="info")

            # System information
            self.append_output(
                f"📋 System: {platform.system()} {platform.release()}\n", tag="info"
            )
            self.append_output(
                f"🐍 Python: {sys.version.split()[0]} ({sys.executable})\n", tag="info"
            )
            self.append_output(f"📁 Working Directory: {Path.cwd()}\n", tag="info")
            self.append_output("\n", tag="info")

            # Check flacr.py script
            flacr_script = Path.cwd() / "flacr.py"
            if flacr_script.exists():
                self.append_output("✅ flacr.py found\n", tag="success")

                # Validate script syntax
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "py_compile", str(flacr_script)],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        self.append_output(
                            "✅ flacr.py syntax validated\n", tag="success"
                        )
                    else:
                        self.append_output(
                            f"❌ flacr.py syntax error: {result.stderr}\n", tag="error"
                        )

                except Exception as e:
                    self.append_output(
                        f"⚠️  Could not validate flacr.py syntax: {e}\n", tag="warn"
                    )
            else:
                self.append_output(
                    f"❌ flacr.py not found in {Path.cwd()}\n", tag="error"
                )
                self.append_output(
                    "   Please ensure flacr.py is in the same directory as this GUI.\n",
                    tag="error",
                )

            # Check for required tools (optional, as flacr.py will check these)
            tools_to_check = ["flac", "metaflac"]
            for tool in tools_to_check:
                try:
                    result = subprocess.run(
                        [tool, "--version"], capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        version_line = (
                            result.stderr.split("\n")[0]
                            if result.stderr
                            else result.stdout.split("\n")[0]
                        )
                        self.append_output(
                            f"✅ {tool}: {version_line}\n", tag="success"
                        )
                    else:
                        self.append_output(f"⚠️  {tool}: Check failed\n", tag="warn")
                except FileNotFoundError:
                    self.append_output(f"⚠️  {tool}: Not found in PATH\n", tag="warn")
                except Exception as e:
                    self.append_output(f"⚠️  {tool}: Check error: {e}\n", tag="warn")

            # Usage instructions
            self.append_output("\n" + "=" * 60 + "\n", tag="info")
            self.append_output("📖 USAGE INSTRUCTIONS\n", tag="info")
            self.append_output("=" * 60 + "\n", tag="info")
            self.append_output(
                "1. 📁 Click 'Browse Directory' to select a folder with FLAC files\n",
                tag="info",
            )
            self.append_output(
                "2. ⚙️  Configure processing options as needed\n", tag="info"
            )
            self.append_output("3. ▶️  Click 'Run' to start processing\n", tag="info")
            self.append_output(
                "4. 🛑 Use 'Cancel' to stop processing if needed\n", tag="info"
            )
            self.append_output(
                "\n💡 Tip: The log will show detailed progress and any issues encountered.\n",
                tag="info",
            )
            self.append_output("=" * 60 + "\n\n", tag="info")

            # Set ready status
            if hasattr(self, "progress_label"):
                self.progress_label.config(text="Ready - Select directory to begin")

            logger.info("Environment validation completed")

        except Exception as e:
            logger.error(f"Environment validation failed: {e}")
            logger.error(traceback.format_exc())
            if hasattr(self, "append_output"):
                self.append_output(
                    f"❌ Environment validation error: {e}\n", tag="error"
                )

    def on_close(self):
        """Handle application closing with proper cleanup"""
        try:
            logger.info("Application close requested")

            # Check if process is running
            if self.process_active and hasattr(self, "process") and self.process:
                response = messagebox.askyesno(
                    "Process Running",
                    "A FLAC processing operation is currently running.\n\n"
                    "Do you want to cancel it and exit?",
                    icon="warning",
                )

                if response:
                    logger.info("User chose to cancel process and exit")
                    try:
                        self.cancel_process()
                        # Give some time for cleanup
                        self.after(1000, self._force_close)
                    except Exception as e:
                        logger.error(f"Error cancelling process: {e}")
                        self._force_close()
                else:
                    logger.info("User chose to keep process running")
                    return
            else:
                self._force_close()

        except Exception as e:
            logger.error(f"Error during application close: {e}")
            self._force_close()

    def _force_close(self):
        """Force application close with cleanup"""
        try:
            logger.info("Forcing application close")

            # Save settings
            try:
                self.save_settings()
            except Exception as e:
                logger.error(f"Error saving settings: {e}")

            # Final cleanup
            self._cleanup_process()

            # Close window
            self.quit()
            self.destroy()

        except Exception as e:
            logger.error(f"Error during force close: {e}")
            try:
                self.destroy()
            except:
                pass

    def create_widgets(self):
        self.grid_rowconfigure(6, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Directory selection
        dir_frame = tk.Frame(self)
        dir_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        dir_frame.grid_columnconfigure(1, weight=1)
        tk.Label(dir_frame, text="Directory:").grid(row=0, column=0, sticky="w")
        self.dir_var = tk.StringVar(value=os.getcwd())
        self.dir_entry = tk.Entry(dir_frame, textvariable=self.dir_var, width=50)
        self.dir_entry.grid(row=0, column=1, sticky="ew")
        tk.Button(dir_frame, text="Browse...", command=self.browse_dir).grid(
            row=0, column=2, padx=(5, 0)
        )

        # Options
        self.options_frame = tk.LabelFrame(self, text="Options")
        self.options_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        for i in range(0, 4):
            self.options_frame.grid_columnconfigure(i, weight=1)

        self.j_var = tk.BooleanVar()
        self.j_check = tk.Checkbutton(
            self.options_frame,
            text="Encode 1 file at a time with multi-threading (-j)",
            variable=self.j_var,
            command=self.update_option_states,
        )
        self.j_check.grid(row=0, column=0, sticky="w")

        self.l_var = tk.BooleanVar()
        self.l_check = tk.Checkbutton(
            self.options_frame, text="Log errors to flacr.log (-l)", variable=self.l_var
        )
        self.l_check.grid(row=0, column=1, sticky="w")

        self.m_label = tk.Label(self.options_frame, text="Thread count (-m):")
        self.m_label.grid(row=1, column=0, sticky="w")
        self.m_var = tk.IntVar(value=1)
        self.m_spin = tk.Spinbox(
            self.options_frame,
            from_=1,
            to=os.cpu_count(),
            textvariable=self.m_var,
            width=5,
        )
        self.m_spin.grid(row=1, column=1, sticky="w")

        self.p_var = tk.BooleanVar()
        self.p_check = tk.Checkbutton(
            self.options_frame, text="Show progress bars (-p)", variable=self.p_var
        )
        self.p_check.grid(row=1, column=2, sticky="w")

        self.r_var = tk.BooleanVar()
        self.r_check = tk.Checkbutton(
            self.options_frame, text="Calculate replay gain (-r)", variable=self.r_var
        )
        self.r_check.grid(row=2, column=0, sticky="w")

        self.s_var = tk.BooleanVar()
        self.s_check = tk.Checkbutton(
            self.options_frame,
            text="Only scan current folder (-s)",
            variable=self.s_var,
        )
        self.s_check.grid(row=2, column=1, sticky="w")

        self.t_var = tk.BooleanVar()
        self.t_check = tk.Checkbutton(
            self.options_frame,
            text="Test only, skip recompression (-t)",
            variable=self.t_var,
        )
        self.t_check.grid(row=2, column=2, sticky="w")

        self.Q_var = tk.BooleanVar()
        self.Q_check = tk.Checkbutton(
            self.options_frame,
            text="Quick mode (-Q)",
            variable=self.Q_var,
            command=self.update_option_states,
        )
        self.Q_check.grid(row=3, column=0, sticky="w")

        self.S_var = tk.BooleanVar()
        self.S_check = tk.Checkbutton(
            self.options_frame,
            text="Sequential mode (-S)",
            variable=self.S_var,
            command=self.update_option_states,
        )
        self.S_check.grid(row=3, column=1, sticky="w")

        self.E_var = tk.BooleanVar()
        self.E_check = tk.Checkbutton(
            self.options_frame, text="Check ENCODER metadata (-E)", variable=self.E_var
        )
        self.E_check.grid(row=3, column=2, sticky="w")

        # Progress bar and label
        self.progress_frame = tk.Frame(self)
        self.progress_frame.grid(row=2, column=0, pady=10, padx=10, sticky="ew")
        self.progress_label = tk.Label(
            self.progress_frame,
            text="Ready",
            anchor="w",
            bg="#f0f0f0",
            relief="sunken",
            padx=5,
        )
        self.progress_label.pack(fill="x", side="top")
        self.progress = ttk.Progressbar(
            self.progress_frame, orient="horizontal", mode="determinate", length=400
        )
        self.progress.pack(fill="x", side="top", pady=(2, 0))

        # Run and log buttons
        btn_frame = tk.Frame(self)
        btn_frame.grid(row=3, column=0, pady=5, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        self.run_button = tk.Button(btn_frame, text="Run", command=self.run_flacr)
        self.run_button.grid(row=0, column=0, padx=5, sticky="w")
        self.cancel_button = tk.Button(
            btn_frame, text="Cancel", command=self.cancel_flacr, state="disabled"
        )
        self.cancel_button.grid(row=0, column=1, padx=5, sticky="w")
        self.log_button = tk.Button(
            btn_frame, text="View Error Log", command=self.open_error_log
        )
        self.log_button.grid(row=0, column=2, padx=5, sticky="w")
        self.help_button = tk.Button(btn_frame, text="Help", command=self.show_help)
        self.help_button.grid(row=0, column=3, padx=5, sticky="w")
        self.copy_cmd_button = tk.Button(
            btn_frame, text="Copy CLI Command", command=self.copy_cli_command
        )
        self.copy_cmd_button.grid(row=0, column=4, padx=5, sticky="w")

        # Output box with tag for error highlighting
        self.output_text = tk.Text(
            self, height=15, width=80, state="normal", wrap="word"
        )
        self.output_text.grid(row=4, column=0, padx=10, pady=5, sticky="nsew")
        self.output_text.tag_configure("error", foreground="red")
        self.output_text.tag_configure("warn", foreground="orange")
        self.output_text.tag_configure("bold", font=("TkDefaultFont", 10, "bold"))
        self.output_text.tag_configure("skipped", foreground="blue")

        # Make output box expandable
        self.grid_rowconfigure(4, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def browse_dir(self):
        """Browse for directory with better error handling"""
        try:
            current_dir = self.dir_var.get()

            # Validate current directory
            if not current_dir or not Path(current_dir).exists():
                current_dir = str(Path.home())

            directory = filedialog.askdirectory(
                initialdir=current_dir, title="Select directory containing FLAC files"
            )

            if directory:
                dir_path = Path(directory)

                # Validate directory permissions
                if not dir_path.is_dir():
                    messagebox.showerror(
                        "Invalid Directory", "Selected path is not a directory."
                    )
                    return

                if not os.access(str(dir_path), os.R_OK):
                    messagebox.showerror(
                        "Permission Error", "Cannot read from selected directory."
                    )
                    return

                self.dir_var.set(str(dir_path))
                logger.info(f"Directory selected: {directory}")

                # Give user feedback about the selection
                try:
                    flac_count = len(list(dir_path.rglob("*.flac")))
                    if flac_count > 0:
                        self.progress_label.config(
                            text=f"Directory selected - Found {flac_count} FLAC files"
                        )
                    else:
                        self.progress_label.config(
                            text="Directory selected - No FLAC files found"
                        )
                except Exception as e:
                    logger.warning(f"Could not count FLAC files: {e}")
                    self.progress_label.config(text="Directory selected")

        except Exception as e:
            logger.error(f"Error in browse_dir: {e}")
            messagebox.showerror("Error", f"Failed to select directory: {e}")

    def run_flacr(self):
        """Run flacr with comprehensive validation and error handling"""
        try:
            logger.info("Run button clicked - starting validation")
            print("DEBUG: Run button clicked!")
            
            # Validate dependencies first
            if not self.check_dependencies():
                logger.warning("Dependencies check failed")
                return

            # Validate directory
            directory = Path(self.dir_var.get())
            logger.info(f"Validating directory: {directory}")
            
            if not directory.exists():
                messagebox.showerror(
                    "Invalid Directory", "Selected directory does not exist."
                )
                return

            if not directory.is_dir():
                messagebox.showerror(
                    "Invalid Directory", "Selected path is not a directory."
                )
                return

            if not os.access(str(directory), os.R_OK):
                messagebox.showerror(
                    "Permission Error", "Cannot read from selected directory."
                )
                return

            logger.info("Directory validation passed")

            # Check for tqdm if progress is enabled
            if self.p_var.get() and not self.tqdm_installed():
                response = messagebox.askyesno(
                    "tqdm not installed",
                    "tqdm is required for progress bars. Continue anyway?\n\n"
                    "Install with: pip install tqdm",
                )
                if not response:
                    return

            # Check FLAC version for threading options
            if self.j_var.get() or self.S_var.get():
                if not self.flac_supports_threads():
                    messagebox.showwarning(
                        "FLAC Version",
                        "FLAC >=1.5.0 is required for multi-threaded encoding (-j/-S).\n"
                        "Please upgrade FLAC or disable threading options.",
                    )
                    return

            # Save settings before starting
            self.save_settings()

            # Initialize process state
            self.start_time = time.time()
            self.files_processed = 0
            self.total_files = None
            self._completion_handled = False

            logger.info("Updating UI state")
            # Update UI state
            self.run_button.config(state="disabled")
            self.cancel_button.config(state="normal")
            self.progress_label.config(text="Initializing...")

            # Clear and prepare output
            self._prepare_output()

            # Build command arguments
            args = self.build_args()
            logger.info(f"Starting flacr with args: {args}")
            print(f"DEBUG: Command args: {args}")

            # Start processing in background thread
            logger.info(f"Starting thread with args: {args}")
            threading.Thread(
                target=self._run_flacr_thread,
                args=(args,),
                daemon=True,
                name="FlacProcessorThread",
            ).start()
            logger.info("Background thread started successfully")

        except Exception as e:
            logger.error(f"Error starting flacr: {e}")
            logger.error(traceback.format_exc())
            messagebox.showerror("Error", f"Failed to start processing: {e}")
            self.run_button.config(state="normal")
            self.cancel_button.config(state="disabled")

    def _prepare_output(self):
        """Prepare output text widget for new run"""
        try:
            self.output_text.config(state="normal")
            self.output_text.delete(1.0, tk.END)

            # Add startup information
            self.output_text.insert(tk.END, "FLAC Recompressor Starting...\n", "bold")
            self.output_text.insert(tk.END, f"Directory: {self.dir_var.get()}\n")
            self.output_text.insert(
                tk.END, f'Started at: {time.strftime("%Y-%m-%d %H:%M:%S")}\n'
            )
            self.output_text.insert(
                tk.END,
                "Note: Timeouts are dynamic based on operation (5min-2hrs).\n",
                "warn",
            )
            self.output_text.insert(tk.END, "-" * 50 + "\n")

            self.output_text.config(state="disabled")
            self.progress["value"] = 0
            self.progress_label.config(text="Initializing...")

        except Exception as e:
            logger.error(f"Error preparing output: {e}")

    def cancel_flacr(self):
        """Cancel the running flacr process"""
        if self.process and self.process.poll() is None:
            try:
                self.append_output("\n[CANCELLED BY USER]\n", tag="error")
                self.process_active = False  # Signal threads to stop
                self._terminate_process_safely()
            except Exception as e:
                self.append_output(f"Error during cancellation: {e}\n", tag="error")
            finally:
                self.run_button.config(state="normal")
                self.cancel_button.config(state="disabled")

    def tqdm_installed(self):
        try:
            import tqdm

            return True
        except ImportError:
            return False

    def flac_supports_threads(self):
        flac_path = shutil.which("flac")
        if not flac_path:
            return False
        try:
            out = subprocess.check_output(
                [flac_path, "--version"], encoding="utf-8", stderr=subprocess.STDOUT
            )
            m = re.search(r"flac (\d+)\.(\d+)\.(\d+)", out)
            if m:
                major, minor, patch = map(int, m.groups())
                return (major > 1) or (major == 1 and minor >= 5)
        except Exception:
            return False
        return False

    def build_args(self):
        """Build command line arguments for flacr.py"""
        args = [sys.executable, str(SCRIPT_PATH)]  # Convert Path to string
        if self.dir_var.get():
            args += ["-d", self.dir_var.get()]
        if self.j_var.get():
            args.append("-j")
        if self.l_var.get():
            args.append("-l")
        if self.m_var.get():
            args += ["-m", str(self.m_var.get())]
        if self.p_var.get():
            args.append("-p")
        if self.r_var.get():
            args.append("-r")
        if self.s_var.get():
            args.append("-s")
        if self.t_var.get():
            args.append("-t")
        if self.Q_var.get():
            args.append("-Q")
        if self.S_var.get():
            args.append("-S")
        if self.E_var.get():
            args.append("-E")
        return args

    def _run_flacr_thread(self, args):
        """Main processing thread with comprehensive error handling"""
        try:
            logger.info("Starting FLAC processing thread")
            logger.info(f"Thread args: {args}")

            # Initialize queue and process state
            self.output_queue = queue.Queue(maxsize=5000)  # Increase queue size for better handling
            self.process_active = True

            # Configure subprocess creation
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            # Start subprocess with proper error handling
            try:
                logger.info(f"Starting subprocess with args: {args}")
                self.process = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,  # Line buffering
                    creationflags=creation_flags,
                    universal_newlines=True,
                    env=dict(os.environ, PYTHONUNBUFFERED="1"),  # Force unbuffered output
                    cwd=str(Path(self.dir_var.get()).parent),  # Set working directory
                )
                logger.info(f"Process started with PID: {self.process.pid}")

            except (OSError, subprocess.SubprocessError) as e:
                logger.error(f"Failed to start subprocess: {e}")
                self.append_output(
                    f"Error: Failed to start process: {e}\n", tag="error"
                )
                return

            # Start output reading thread
            logger.info("Starting output reader thread")
            output_thread = threading.Thread(
                target=self._read_process_output, daemon=True, name="OutputReaderThread"
            )
            output_thread.start()

            # Process output with improved error handling
            logger.info("Starting output processing loop")
            self._process_output_loop()

            # Wait for process completion
            logger.info("Waiting for process completion")
            self._wait_for_completion()

        except Exception as e:
            logger.error(f"Critical error in process thread: {e}")
            logger.error(traceback.format_exc())
            self.append_output(f"Critical error: {e}\n", tag="error")
        finally:
            logger.info("Cleaning up process")
            self._cleanup_process()

    def _wait_for_completion(self):
        """Wait for process completion with proper error handling"""
        try:
            if self.process:
                logger.info("Waiting for process completion")
                
                # Wait with timeout
                try:
                    exit_code = self.process.wait(timeout=30)
                    logger.info(f"Process completed with exit code: {exit_code}")
                    
                except subprocess.TimeoutExpired:
                    logger.warning("Process did not complete within timeout, terminating")
                    self._terminate_process_safely()
                    exit_code = -1
                
                # Handle completion status based on exit code
                self._handle_process_completion(exit_code)
                
        except Exception as e:
            logger.error(f"Error waiting for process completion: {e}")
            self.append_output(f'Error during process completion: {e}\n', tag='error')

    def _process_output_loop(self):
        """Main output processing loop with improved timeout handling"""
        total_files = None
        processed = 0
        current_file = ""
        last_output_time = time.time()
        last_progress_time = time.time()
        last_gui_update = time.time()
        current_operation = "Starting"

        # Dynamic timeout settings
        operation_timeouts = {
            "scanning": 600,  # 10 minutes for scanning
            "checking": 1800,  # 30 minutes for checking files
            "encoding": 3600,  # 1 hour for encoding
            "verifying": 1800,  # 30 minutes for verification
            "rsgain": 7200,  # 2 hours for replay gain
            "default": 600,  # 10 minutes default
        }

        consecutive_errors = 0
        max_consecutive_errors = 5
        gui_update_interval = 0.1  # Update GUI max every 100ms

        while self.process_active:
            try:
                # Check if process finished
                if self.process and self.process.poll() is not None:
                    logger.info("Process completed, stopping output loop")
                    self.process_active = False
                    break

                # Get output with timeout - process multiple lines if available
                lines_to_process = []
                try:
                    # Get first line with timeout
                    line = self.output_queue.get(timeout=0.5)
                    if line is None:  # End of output signal
                        break
                    lines_to_process.append(line)
                    
                    # Get additional lines without blocking (batch processing)
                    while len(lines_to_process) < 50:  # Limit batch size
                        try:
                            line = self.output_queue.get_nowait()
                            if line is None:  # End of output signal
                                break
                            lines_to_process.append(line)
                        except queue.Empty:
                            break

                    # Emergency queue drain if it's getting too full
                    if self.output_queue.qsize() > 4000:  # 80% of max capacity
                        logger.warning(f"Queue very full ({self.output_queue.qsize()}), draining excess")
                        drained = 0
                        while self.output_queue.qsize() > 2000 and drained < 1000:
                            try:
                                self.output_queue.get_nowait()
                                drained += 1
                            except queue.Empty:
                                break
                        logger.warning(f"Drained {drained} excess queue items")

                    consecutive_errors = 0  # Reset error counter on successful read
                    current_time = time.time()
                    last_output_time = current_time

                    # Process all lines in batch
                    for line in lines_to_process:
                        if line is None:
                            break
                        result = self._process_output_line(
                            line, current_time, last_progress_time
                        )
                        if result:
                            operation, file_info, progress_info = result
                            if operation:
                                current_operation = operation
                                last_progress_time = current_time
                            if file_info:
                                current_file, processed = file_info
                                last_progress_time = current_time
                            if progress_info:
                                total_files = progress_info
                    
                    # Rate-limited GUI updates to prevent overwhelming tkinter
                    if current_time - last_gui_update >= gui_update_interval:
                        self.after_idle(lambda: None)  # Force GUI refresh
                        last_gui_update = current_time

                except queue.Empty:
                    # Handle timeout conditions
                    current_time = time.time()
                    timeout_result = self._handle_timeout(
                        current_time,
                        last_output_time,
                        last_progress_time,
                        current_operation,
                        current_file,
                        operation_timeouts,
                    )

                    if timeout_result == "terminate":
                        break
                    elif timeout_result == "reset_progress":
                        last_progress_time = current_time

            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    f"Error in output loop (attempt {consecutive_errors}): {e}"
                )

                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Too many consecutive errors, terminating")
                    self.append_output(
                        f"Too many errors occurred, stopping process.\n", tag="error"
                    )
                    break

                time.sleep(0.5)  # Brief pause before retry

    def _process_output_line(self, line, current_time, last_progress_time):
        """Process a single output line and extract information"""
        try:
            # Only append output for important lines, not every single line
            # to prevent GUI update overload
            important_line = self._is_important_output_line(line)
            if important_line:
                logger.debug(f"Processing important output line: {line.strip()}")
                self.append_output(line)

            # Detect current operation
            operation = self._detect_current_operation(line)
            if operation:
                logger.debug(f"Detected operation: {operation}")

            # Extract file information
            file_info = None
            file_data = self._extract_file_info(line)
            if file_data:
                file_path, operation_type = file_data
                logger.debug(f"Extracted file info: {file_path}, {operation_type}")

                # Update file processing count
                if operation_type in ["processing", "encoding", "verifying"]:
                    self.files_processed += 1

                status_text = f"{operation_type.title()}: {Path(file_path).name}"
                self.update_progress(
                    self.files_processed,
                    self.total_files or self.files_processed,
                    file_path,
                    status_text,
                )
                file_info = (file_path, self.files_processed)

            # Extract total files count
            progress_info = None
            if self.total_files is None:
                summary_match = re.search(r"(\d+) flac files", line)
                if summary_match:
                    self.total_files = int(summary_match.group(1))
                    self.progress["maximum"] = self.total_files
                    self.progress_label.config(
                        text=f"Found {self.total_files} FLAC files"
                    )
                    progress_info = self.total_files
                    logger.debug(f"Found total files: {self.total_files}")

            # Handle rsgain output
            if self._is_rsgain_output(line):
                operation = "rsgain"
                rsgain_status = self._parse_rsgain_output(line)
                if rsgain_status:
                    self.progress_label.config(text=f"Replay Gain: {rsgain_status}")

            return operation, file_info, progress_info

        except Exception as e:
            logger.error(f"Error processing output line: {e}")
            return None

    def _is_important_output_line(self, line):
        """Determine if this output line should be shown in GUI to reduce spam"""
        line_lower = line.lower().strip()
        
        # Always show these important line types
        important_patterns = [
            # Progress and status messages
            r'scanning|found \d+ flac files|processing|completed',
            # File operations
            r'encoding|verifying|checking|transcoding',
            # Errors and warnings
            r'error|warning|failed|problem',
            # Summary information
            r'total|summary|finished|done',
            # Replay gain operations
            r'rsgain|replay gain|calculating gain',
            # Important file mentions (not every progress line)
            r'\.flac.*->.*\.flac',
        ]
        
        # Skip verbose progress indicators and repeated messages
        skip_patterns = [
            r'^\s*\d+%\s*$',  # Just percentage numbers
            r'^\s*\|\s*[▉▊▋▌▍▎▏\s]*\|\s*\d+%',  # Progress bars
            r'^\s*[\.]{3,}',  # Multiple dots
            r'reading.*metadata',  # Verbose metadata reading
        ]
        
        # Check if we should skip this line
        for pattern in skip_patterns:
            if re.search(pattern, line_lower):
                return False
        
        # Check if this is an important line
        for pattern in important_patterns:
            if re.search(pattern, line_lower):
                return True
        
        # For debugging, show some lines but not all
        # Show every 50th line of unmatched content
        import random
        return random.randint(1, 50) == 1

    def _handle_timeout(
        self,
        current_time,
        last_output_time,
        last_progress_time,
        current_operation,
        current_file,
        operation_timeouts,
    ):
        """Handle timeout conditions with appropriate user feedback"""
        try:
            current_timeout = operation_timeouts.get(
                current_operation.lower(), operation_timeouts["default"]
            )
            time_since_output = current_time - last_output_time
            time_since_progress = current_time - last_progress_time

            # Show what we're waiting for
            if time_since_output > 30:  # After 30 seconds of no output
                waiting_text = f"Waiting for {current_operation}"
                if current_file:
                    waiting_text += f" on {Path(current_file).name}"

                elapsed = time.time() - self.start_time if self.start_time else 0
                waiting_text += (
                    f" ({int(time_since_output)}s, total: {int(elapsed//60)}m)"
                )
                self.progress_label.config(text=waiting_text)

            # Check for timeout
            if time_since_output > current_timeout:
                logger.warning(
                    f"Timeout after {current_timeout}s during {current_operation}"
                )
                self.append_output(
                    f"\n[TIMEOUT] No output for {current_timeout//60} minutes during {current_operation}.\n",
                    tag="error",
                )
                if current_file:
                    self.append_output(
                        f"[TIMEOUT] Last file: {Path(current_file).name}\n", tag="error"
                    )
                self._terminate_process_safely()
                return "terminate"

            # Progress timeout warning
            if time_since_progress > current_timeout * 2:
                logger.warning(
                    f"No progress for {current_timeout*2}s on {current_operation}"
                )
                self.append_output(
                    f"\n[WARNING] No progress for {(current_timeout*2)//60} minutes on {current_operation}\n",
                    tag="warn",
                )
                if current_file:
                    self.append_output(
                        f"[WARNING] Current file: {Path(current_file).name}\n",
                        tag="warn",
                    )
                return "reset_progress"

            # Keep GUI responsive
            self.update_idletasks()
            return "continue"

        except Exception as e:
            logger.error(f"Error in timeout handling: {e}")
            return "continue"

    def _read_process_output(self):
        """Read process output and put it in queue with error handling"""
        try:
            logger.info("Starting output reader thread")

            if not self.process or not self.process.stdout:
                logger.error("No process or stdout available")
                return

            buffer_size = 8192  # Larger buffer for efficiency
            partial_line = ""
            lines_read = 0
            dropped_lines = 0  # Track dropped lines to reduce log spam

            try:
                for line in iter(self.process.stdout.readline, ""):
                    if not self.process_active:
                        logger.info(f"Process no longer active, stopping output reader after {lines_read} lines")
                        break

                    try:
                        lines_read += 1
                        # Reduce debug logging frequency to prevent spam
                        if lines_read % 100 == 0:
                            logger.debug(f"Read {lines_read} lines so far")
                        
                        # Handle partial lines properly
                        if line.endswith("\n"):
                            full_line = partial_line + line
                            partial_line = ""

                            # Put line in queue with size check - batch processing approach
                            try:
                                self.output_queue.put_nowait(full_line)
                                # Only log every 100th successful line to reduce spam
                                if lines_read % 100 == 0:
                                    logger.debug(f"Put line {lines_read} in queue")
                            except queue.Full:
                                # Drop line silently when queue is full to prevent log spam
                                # Only log every 100th dropped line
                                dropped_lines += 1
                                if dropped_lines % 100 == 0:
                                    logger.warning(f"Output queue full, dropped {dropped_lines} lines")
                        else:
                            partial_line += line

                    except Exception as e:
                        logger.error(f"Error processing output line {lines_read}: {e}")

                # Handle any remaining partial line
                if partial_line:
                    try:
                        self.output_queue.put_nowait(partial_line + "\n")
                        logger.debug(f"Put final partial line in queue")
                    except queue.Full:
                        logger.warning("Queue full, dropped final partial line")

                logger.info(f"Finished reading process output. Total lines read: {lines_read}")

            except Exception as e:
                logger.error(f"Error reading process output: {e}")

        except Exception as e:
            logger.error(f"Critical error in output reader: {e}")
        finally:
            try:
                self.output_queue.put(None)  # Signal end of output
                logger.info("Output reader thread finished")
            except:
                pass
        """Read process output in a separate thread to prevent blocking - using best practices"""
        try:
            if not self.process or not self.process.stdout:
                return

            # Use proper file handling with context management principles
            stdout = self.process.stdout

            while self.process_active and self.process.poll() is None:
                try:
                    # Read line with proper error handling
                    line = stdout.readline()

                    if line:
                        # Ensure we have clean text
                        line = line.rstrip("\r\n") + "\n"
                        self.output_queue.put(line)
                    else:
                        # Check if process is still running
                        if self.process.poll() is not None:
                            break
                        # Brief pause to prevent busy waiting
                        time.sleep(0.01)

                except (ValueError, OSError) as e:
                    # Handle pipe closure or other I/O errors
                    self.output_queue.put(f"Process communication error: {e}\n")
                    break
                except Exception as e:
                    self.output_queue.put(f"Unexpected output reading error: {e}\n")
                    break

            # Read any remaining output using best practices
            try:
                # Set stdout to non-blocking if possible (Unix only)
                if (
                    HAS_FCNTL
                    and hasattr(os, "O_NONBLOCK")
                    and hasattr(stdout, "fileno")
                ):
                    try:
                        fd = stdout.fileno()
                        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                    except (OSError, AttributeError):
                        pass  # Not available or accessible

                # Read remaining output with timeout
                remaining_lines = []
                timeout_start = time.time()

                while time.time() - timeout_start < 2.0:  # 2 second timeout
                    try:
                        line = stdout.readline()
                        if line:
                            remaining_lines.append(line.rstrip("\r\n") + "\n")
                        else:
                            break
                    except (ValueError, OSError):
                        break

                # Add remaining lines to queue
                for line in remaining_lines:
                    self.output_queue.put(line)

            except Exception as e:
                # Don't add error for remaining output - it's expected during termination
                pass

            # Signal end of output
            self.output_queue.put(None)

        except Exception as e:
            self.output_queue.put(f"Critical output thread error: {e}\n")
            self.output_queue.put(None)
        finally:
            # Ensure stdout is properly handled
            try:
                if (
                    self.process
                    and self.process.stdout
                    and not self.process.stdout.closed
                ):
                    # Don't close stdout here - let subprocess handle it
                    pass
            except Exception:
                pass

    def _detect_current_operation(self, line):
        """Detect what operation is currently being performed"""
        line_lower = line.lower()

        if "scanning" in line_lower or "searching" in line_lower:
            return "scanning"
        elif "checking" in line_lower and (
            "files" in line_lower or "metadata" in line_lower
        ):
            return "checking"
        elif "encoding" in line_lower or "recompress" in line_lower:
            return "encoding"
        elif "verifying" in line_lower or "testing" in line_lower:
            return "verifying"
        elif "rsgain" in line_lower or "replay gain" in line_lower:
            return "rsgain"
        elif "calculating" in line_lower:
            return "rsgain"

        return None

    def _extract_file_info(self, line):
        """Extract file information and operation type from output line"""
        patterns = [
            # Core processing patterns
            (r"Processing:\s*(.+\.flac)", "processing"),
            (r"Verifying:\s*(.+\.flac)", "verifying"),
            (r"Encoding:\s*(.+\.flac)", "encoding"),
            (r"Checking:\s*(.+\.flac)", "checking"),
            (r"Successfully processed:\s*(.+\.flac)", "completed"),
            # File status patterns
            (r"Will re-encode:\s*(.+\.flac)", "queued"),
            (r"Skipping (.+\.flac):", "skipped"),
            (r"(.+\.flac): already encoded", "skipped"),
            # Error patterns
            (r"Error processing (.+\.flac):", "error"),
            (r"Verification error for (.+\.flac):", "error"),
            # Generic file mention
            (r'([^\\/:*?"<>|\s]+\.flac)', "mentioned"),
        ]

        for pattern, operation_type in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                file_path = match.group(1).strip()
                # Clean up path - remove quotes and extra spaces
                file_path = file_path.strip("\"'")
                return file_path, operation_type

        return None

    def _is_rsgain_output(self, line):
        """Check if line is rsgain output"""
        rsgain_indicators = [
            "rsgain",
            "replay gain",
            "loudness",
            "lufs",
            "peak",
            "scanning",
            "album gain",
            "track gain",
        ]
        line_lower = line.lower()
        return any(indicator in line_lower for indicator in rsgain_indicators)

    def _parse_rsgain_output(self, line):
        """Parse rsgain output for status information"""
        line_lower = line.lower()

        # Look for progress indicators
        if "scanning" in line_lower:
            # Extract file being scanned
            file_match = re.search(r'([^\\/:*?"<>|\s]+\.flac)', line, re.IGNORECASE)
            if file_match:
                return f"Scanning {os.path.basename(file_match.group(1))}"
            return "Scanning files..."

        elif "writing" in line_lower or "updating" in line_lower:
            return "Writing replay gain tags..."

        elif "album" in line_lower and "gain" in line_lower:
            return "Calculating album gain..."

        elif "track" in line_lower and "gain" in line_lower:
            return "Calculating track gain..."

        elif "complete" in line_lower or "done" in line_lower:
            return "Replay gain calculation complete"

        # Look for progress numbers
        progress_match = re.search(r"(\d+)/(\d+)", line)
        if progress_match:
            current, total = progress_match.groups()
            return f"Progress: {current}/{total}"

        return None

    def _terminate_process_safely(self):
        """Safely terminate the process with comprehensive cleanup"""
        try:
            logger.info("Safely terminating process")

            if hasattr(self, "process") and self.process:
                # Try graceful termination first
                try:
                    if self.process.poll() is None:  # Process is still running
                        logger.info("Sending SIGTERM to process")
                        self.process.terminate()

                        # Wait briefly for graceful shutdown
                        try:
                            self.process.wait(timeout=5)
                            logger.info("Process terminated gracefully")
                        except subprocess.TimeoutExpired:
                            logger.warning(
                                "Process did not terminate gracefully, forcing kill"
                            )
                            self.process.kill()
                            try:
                                self.process.wait(timeout=5)
                                logger.info("Process killed successfully")
                            except subprocess.TimeoutExpired:
                                logger.error("Failed to kill process")

                except Exception as e:
                    logger.error(f"Error during process termination: {e}")

            # Signal end of processing
            self.process_active = False
            if hasattr(self, "output_queue"):
                try:
                    self.output_queue.put(None)  # Signal end
                except:
                    pass

        except Exception as e:
            logger.error(f"Error in safe termination: {e}")

    def _read_remaining_output(self):
        """Read any remaining output from the process - handled by queue system"""
        # With the queue-based approach, this is handled by the output thread
        pass

    def _handle_process_completion(self, exit_code):
        """Handle process completion with appropriate user feedback"""
        try:
            elapsed = time.time() - self.start_time if self.start_time else 0
            elapsed_str = f"{int(elapsed//60)}m {int(elapsed%60)}s"

            if exit_code == 0:
                self.append_output(
                    f"\n[COMPLETED] Process finished successfully in {elapsed_str}\n",
                    tag="success",
                )
                self.progress_label.config(
                    text=f"Completed successfully ({elapsed_str})"
                )

                # Final progress update
                if self.total_files and self.files_processed:
                    self.update_progress(
                        self.total_files, self.total_files, "", "Complete"
                    )

            elif exit_code is None or exit_code < 0:
                self.append_output(
                    f"\n[CANCELLED] Process was cancelled after {elapsed_str}\n",
                    tag="warn",
                )
                self.progress_label.config(text=f"Cancelled ({elapsed_str})")

            else:
                self.append_output(
                    f"\n[ERROR] Process failed with exit code {exit_code} after {elapsed_str}\n",
                    tag="error",
                )
                self.progress_label.config(text=f"Failed (exit code: {exit_code})")

            # Log completion stats
            logger.info(
                f"Process completed: exit_code={exit_code}, files_processed={self.files_processed}, elapsed={elapsed_str}"
            )

        except Exception as e:
            logger.error(f"Error handling process completion: {e}")
            self.progress_label.config(text="Completed with errors")

    def append_output(self, text, tag=None):
        """Schedule GUI update in main thread to prevent memory corruption"""
        try:
            # Use after_idle for better GUI responsiveness
            # Since FlacrGUI inherits from tk.Tk, self is the root window
            self.after_idle(self._append_output_safe, text, tag)
        except Exception as e:
            logger.error(f"Error scheduling output update: {e}")
            # Fallback to direct print
            print(f"Output: {text.strip()}")

    def _append_output_safe(self, text, tag=None):
        """Safely append text to output widget with comprehensive error handling"""
        try:
            if not self.output_text or not self.output_text.winfo_exists():
                logger.warning("Output text widget not available")
                return

            self.output_text.config(state="normal")

            # Auto-truncate log if it gets too long to prevent memory issues
            try:
                current_lines = int(self.output_text.index("end-1c").split(".")[0])
                if current_lines > self.max_log_lines:
                    # Remove first chunk of lines to prevent constant truncation
                    lines_to_remove = min(500, current_lines - self.max_log_lines + 200)
                    self.output_text.delete("1.0", f"{lines_to_remove}.0")

                    # Add truncation notice
                    timestamp = time.strftime("%H:%M:%S")
                    truncation_msg = f"[{timestamp}] ... earlier output truncated ({lines_to_remove} lines) ...\n"
                    self.output_text.insert("1.0", truncation_msg, "warn")

            except Exception as e:
                logger.error(f"Error during log truncation: {e}")

            # Enhanced automatic tag detection
            if tag is None:
                text_lower = text.lower()
                if any(
                    keyword in text_lower
                    for keyword in [
                        "error",
                        "failed",
                        "exception",
                        "critical",
                        "traceback",
                    ]
                ):
                    tag = "error"
                elif any(
                    keyword in text_lower
                    for keyword in ["warning", "warn", "skipping", "cannot", "missing"]
                ):
                    tag = "warn"
                elif any(
                    keyword in text_lower
                    for keyword in ["completed", "success", "done", "finished"]
                ):
                    tag = "success"
                elif text.startswith("[") and "]" in text:
                    # Status messages in brackets
                    tag = "info"
                elif "SKIPPED_FLAC:" in text:
                    tag = "skipped"

            # Insert text with proper tag
            try:
                self.output_text.insert(tk.END, text, tag)
                self.output_text.see(tk.END)

                # Periodically update display
                if hasattr(self, "_last_display_update"):
                    if (
                        time.time() - self._last_display_update > 0.1
                    ):  # Update every 100ms max
                        self.output_text.update_idletasks()
                        self._last_display_update = time.time()
                else:
                    self._last_display_update = time.time()

            except Exception as e:
                logger.error(f"Error inserting text to output widget: {e}")

        except Exception as e:
            logger.error(f"Critical error in output append: {e}")
            # Emergency fallback
            try:
                print(f"GUI Error - Output: {text.strip()}")
            except:
                pass
        finally:
            try:
                if self.output_text and self.output_text.winfo_exists():
                    self.output_text.config(state="disabled")
            except:
                pass

    def update_progress(self, value, maximum, current_file=None, status_text=None):
        """Schedule progress update in main thread with error handling and throttling"""
        try:
            # Throttle progress updates to prevent GUI overload
            current_time = time.time()
            if hasattr(self, '_last_progress_update'):
                if current_time - self._last_progress_update < 0.2:  # Max 5 updates per second
                    return
            self._last_progress_update = current_time
            
            self.after_idle(
                self._update_progress_safe, value, maximum, current_file, status_text
            )
        except Exception as e:
            logger.error(f"Error scheduling progress update: {e}")

    def _update_progress_safe(
        self, value, maximum, current_file=None, status_text=None
    ):
        """Safely update progress display with comprehensive validation"""
        try:
            # Validate inputs
            if value is None:
                value = 0
            if maximum is None or maximum <= 0:
                maximum = max(1, value)

            # Ensure value doesn't exceed maximum
            value = min(value, maximum)

            # Update progress bar
            try:
                if self.progress and self.progress.winfo_exists():
                    self.progress["maximum"] = maximum
                    self.progress["value"] = value
            except Exception as e:
                logger.error(f"Error updating progress bar: {e}")

            # Update progress label
            try:
                if self.progress_label and self.progress_label.winfo_exists():
                    if status_text:
                        label_text = status_text
                    else:
                        percentage = (value / maximum * 100) if maximum > 0 else 0
                        label_text = f"Progress: {value}/{maximum} ({percentage:.1f}%)"

                        if current_file:
                            file_name = (
                                Path(current_file).name
                                if isinstance(current_file, (str, Path))
                                else str(current_file)
                            )
                            if len(file_name) > 40:
                                file_name = file_name[:37] + "..."
                            label_text += f" - {file_name}"

                    self.progress_label.config(text=label_text)

            except Exception as e:
                logger.error(f"Error updating progress label: {e}")            # Update window title with progress
            try:
                if maximum > 0 and value > 0:
                    percentage = int(value / maximum * 100)
                    title = f"FLACR GUI - {percentage}% Complete"
                else:
                    title = "FLACR GUI"
                
                if self and self.winfo_exists():
                    self.title(title)
                    
            except Exception as e:
                logger.error(f"Error updating window title: {e}")

        except Exception as e:
            logger.error(f"Critical error in progress update: {e}")

    def _cleanup_process(self):
        """Clean up process resources and reset GUI state"""
        try:
            logger.info("Cleaning up process resources")

            # Clean up process
            self.process_active = False
            if hasattr(self, "process") and self.process:
                try:
                    if self.process.poll() is None:
                        logger.info("Terminating remaining process")
                        self.process.terminate()
                        time.sleep(1)  # Give it time to terminate
                        if self.process.poll() is None:
                            logger.warning("Force killing process")
                            self.process.kill()
                except Exception as e:
                    logger.error(f"Error during process cleanup: {e}")
                finally:
                    self.process = None

            # Clean up queue
            if hasattr(self, "output_queue"):
                try:
                    while not self.output_queue.empty():
                        self.output_queue.get_nowait()
                except:
                    pass

            # Reset GUI state
            self.after(0, self._reset_gui_state)

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def _reset_gui_state(self):
        """Reset GUI state after process completion"""
        try:
            self.run_button.config(state="normal")
            self.cancel_button.config(state="disabled")

            # Reset window title
            if self and self.winfo_exists():
                self.title("FLACR GUI")

            # Reset progress if no completion was detected
            if not hasattr(self, "_completion_handled"):
                if self.files_processed == 0:
                    self.progress_label.config(text="Ready")
                    self.progress["value"] = 0

        except Exception as e:
            logger.error(f"Error resetting GUI state: {e}")

    def _update_progress_safe(
        self, value, maximum, current_file=None, status_text=None
    ):
        try:
            self.progress["maximum"] = maximum
            self.progress["value"] = value

            if status_text:
                # Use provided status text
                if maximum > 0:
                    percentage = value / maximum * 100
                    self.progress_label.config(
                        text=f"{status_text} ({value}/{maximum} - {percentage:.1f}%)"
                    )
                else:
                    self.progress_label.config(text=f"{status_text} ({value} files)")
            elif current_file:
                # Fallback to file-based status
                display_file = os.path.basename(current_file)
                percentage = (value / maximum * 100) if maximum > 0 else 0
                self.progress_label.config(
                    text=f"Processing: {display_file} ({value}/{maximum} - {percentage:.1f}%)"
                )
            elif maximum > 0:
                # Generic progress
                percentage = value / maximum * 100
                self.progress_label.config(
                    text=f"Progress: {value}/{maximum} files ({percentage:.1f}%)"
                )
            else:
                # Unknown progress
                self.progress_label.config(text=f"Processing... ({value} files)")
        except Exception as e:
            print(f"Progress update error: {e}")

    def check_dependencies(self):
        missing = []
        if not shutil.which("flac"):
            missing.append("flac")
        if not shutil.which("metaflac"):
            missing.append("metaflac")
        if self.r_var.get() and not shutil.which("rsgain"):
            missing.append("rsgain")
        if missing:
            messagebox.showerror(
                "Missing Dependencies",
                f'The following tools are missing: {", ".join(missing)}.\nPlease install them and try again.',
            )
            return False
        return True

    def open_error_log(self):
        if not os.path.exists(ERROR_LOG_PATH):
            messagebox.showinfo("Error Log", "No error log found.")
            return
        log_win = tk.Toplevel(self)
        log_win.title("flacr_error.log")
        log_win.geometry("700x400")
        text = tk.Text(log_win, wrap="word")
        text.pack(expand=True, fill="both")
        with open(ERROR_LOG_PATH, encoding="utf8") as f:
            log_content = f.read()
        text.insert("1.0", log_content)
        text.config(state="disabled")

    def show_help(self):
        help_text = (
            "flacr - FLAC Recompressor GUI\n\n"
            "Options:\n"
            "-d: Directory to scan for .flac files.\n"
            "-j: flac >=1.5.0: Encode 1 file at a time with multi-threading (threadcount via -m) instead of encoding multiple files concurrently.\n"
            "-l: Log errors to flacr.log.\n"
            "-m: Number of threads for conversion and replay gain calculation.\n"
            "-p: Show progress bars (requires tqdm).\n"
            "-r: Calculate replay gain (requires rsgain).\n"
            "-s: Only scan the current folder.\n"
            "-t: Test only, skip recompression.\n"
            "-Q: Quick mode: -r -p and -m with all available threads.\n"
            "-S: Sequential mode: -j -r -p and -m 4.\n"
            "-E: Check and fix ENCODER metadata tags.\n\n"
            "Common examples:\n"
            "Test flac files for errors (4 threads):\n"
            "  flacr.py -t -m 4\n"
            "Recompress flac files, no replay gain (4 threads):\n"
            "  flacr.py -m 4\n"
            "Recompress and calculate replay gain (all threads, progress):\n"
            "  flacr.py -Q\n"
            "Sequential mode (4 threads, progress):\n"
            "  flacr.py -S\n"
            "Check and fix ENCODER metadata:\n"
            "  flacr.py -E\n"
            "With directory:\n"
            '  flacr.py -rlp -m 4 -d "D:/Test"\n\n'
            "Documentation:\n"
            "https://github.com/AverageHoarder/flacr\n"
            "https://github.com/complexlogic/rsgain/releases\n"
            "https://xiph.org/flac/download.html\n"
            "https://github.com/tqdm/tqdm\n"
        )
        messagebox.showinfo("Help", help_text)

    def copy_cli_command(self):
        args = self.build_args()
        # Remove sys.executable and script path for CLI copy
        cli_args = args[2:] if args[0].endswith("python.exe") else args[1:]
        cmd = f'python flacr.py {" ".join(map(str, cli_args))}'
        self.clipboard_clear()
        self.clipboard_append(cmd)
        messagebox.showinfo("CLI Command", f"Copied to clipboard:\n{cmd}")

    def update_option_states(self):
        # Quick mode: -Q sets -m to max, -r, -p, disables -S
        if self.Q_var.get():
            self.S_var.set(False)
            self.r_var.set(True)
            self.p_var.set(True)
            self.m_var.set(os.cpu_count())
            self.m_spin.config(state="disabled")
            self.r_check.config(state="disabled")
            self.p_check.config(state="disabled")
            self.S_check.config(state="disabled")
        else:
            self.m_spin.config(state="normal")
            self.r_check.config(state="normal")
            self.p_check.config(state="normal")
            self.S_check.config(state="normal")

        # Sequential mode: -S sets -m 4, -j, -r, -p, disables -Q
        if self.S_var.get():
            self.Q_var.set(False)
            self.r_var.set(True)
            self.p_var.set(True)
            self.j_var.set(True)
            self.m_var.set(4 if os.cpu_count() >= 4 else os.cpu_count())
            self.m_spin.config(state="disabled")
            self.r_check.config(state="disabled")
            self.p_check.config(state="disabled")
            self.j_check.config(state="disabled")
            self.Q_check.config(state="disabled")
        else:
            if not self.Q_var.get():
                self.m_spin.config(state="normal")
                self.r_check.config(state="normal")
                self.p_check.config(state="normal")
            self.j_check.config(state="normal")
            self.Q_check.config(state="normal")

    def save_settings(self):
        # Overwrite the config file from scratch to avoid any duplicate section or option errors
        config = configparser.ConfigParser()
        config.clear()  # Ensure config is empty
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
        with open(CONFIG_PATH, "w") as f:
            config.write(f)

    def load_settings(self):
        config = configparser.ConfigParser()
        if os.path.exists(CONFIG_PATH):
            config.read(CONFIG_PATH)
            if config.has_section("main"):
                self.dir_var.set(config.get("main", "directory", fallback=os.getcwd()))
                self.j_var.set(config.getboolean("main", "j", fallback=False))
                self.l_var.set(config.getboolean("main", "l", fallback=False))
                self.m_var.set(config.getint("main", "m", fallback=1))
                self.p_var.set(config.getboolean("main", "p", fallback=False))
                self.r_var.set(config.getboolean("main", "r", fallback=False))
                self.s_var.set(config.getboolean("main", "s", fallback=False))
                self.t_var.set(config.getboolean("main", "t", fallback=False))
                self.Q_var.set(config.getboolean("main", "Q", fallback=False))
                self.S_var.set(config.getboolean("main", "S", fallback=False))
                self.E_var.set(config.getboolean("main", "E", fallback=False))
                self.update_option_states()

    def on_close(self):
        # Ensure any running process is properly terminated
        if hasattr(self, "process") and self.process and self.process.poll() is None:
            try:
                self.process_active = False
                self.process.terminate()
                # Give it a moment to terminate
                time.sleep(1)
                if self.process.poll() is None:
                    self.process.kill()
            except Exception:
                pass  # Ignore errors during cleanup

        self.save_settings()
        self.destroy()


if __name__ == "__main__":
    app = FlacrGUI()
    app.mainloop()
