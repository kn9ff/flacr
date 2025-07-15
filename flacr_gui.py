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
from io import StringIO

# Import fcntl for Unix systems only
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), 'flacr.py')
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.flacr_gui.ini')
ERROR_LOG_PATH = os.path.join(os.path.dirname(__file__), 'flacr_error.log')

class FlacrGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('flacr - FLAC Recompressor GUI')
        # Set application icon if available
        icon_path = os.path.join(os.path.dirname(__file__), 'flaccheck.ico')
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass
        self.geometry('700x650')
        self.minsize(600, 500)
        self.process = None  # Track running process for cancellation
        self.process_active = False  # Flag to control process threads
        self.max_log_lines = 1000  # Auto-truncate after this many lines
        self.create_widgets()
        self.load_settings()
        self.protocol('WM_DELETE_WINDOW', self.on_close)

    def create_widgets(self):
        self.grid_rowconfigure(6, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Directory selection
        dir_frame = tk.Frame(self)
        dir_frame.grid(row=0, column=0, sticky='ew', padx=10, pady=(10, 0))
        dir_frame.grid_columnconfigure(1, weight=1)
        tk.Label(dir_frame, text='Directory:').grid(row=0, column=0, sticky='w')
        self.dir_var = tk.StringVar(value=os.getcwd())
        self.dir_entry = tk.Entry(dir_frame, textvariable=self.dir_var, width=50)
        self.dir_entry.grid(row=0, column=1, sticky='ew')
        tk.Button(dir_frame, text='Browse...', command=self.browse_dir).grid(row=0, column=2, padx=(5,0))

        # Options
        self.options_frame = tk.LabelFrame(self, text='Options')
        self.options_frame.grid(row=1, column=0, sticky='ew', padx=10, pady=5)
        for i in range(0, 4):
            self.options_frame.grid_columnconfigure(i, weight=1)

        self.j_var = tk.BooleanVar()
        self.j_check = tk.Checkbutton(self.options_frame, text='Encode 1 file at a time with multi-threading (-j)', variable=self.j_var, command=self.update_option_states)
        self.j_check.grid(row=0, column=0, sticky='w')

        self.l_var = tk.BooleanVar()
        self.l_check = tk.Checkbutton(self.options_frame, text='Log errors to flacr.log (-l)', variable=self.l_var)
        self.l_check.grid(row=0, column=1, sticky='w')

        self.m_label = tk.Label(self.options_frame, text='Thread count (-m):')
        self.m_label.grid(row=1, column=0, sticky='w')
        self.m_var = tk.IntVar(value=1)
        self.m_spin = tk.Spinbox(self.options_frame, from_=1, to=os.cpu_count(), textvariable=self.m_var, width=5)
        self.m_spin.grid(row=1, column=1, sticky='w')

        self.p_var = tk.BooleanVar()
        self.p_check = tk.Checkbutton(self.options_frame, text='Show progress bars (-p)', variable=self.p_var)
        self.p_check.grid(row=1, column=2, sticky='w')

        self.r_var = tk.BooleanVar()
        self.r_check = tk.Checkbutton(self.options_frame, text='Calculate replay gain (-r)', variable=self.r_var)
        self.r_check.grid(row=2, column=0, sticky='w')

        self.s_var = tk.BooleanVar()
        self.s_check = tk.Checkbutton(self.options_frame, text='Only scan current folder (-s)', variable=self.s_var)
        self.s_check.grid(row=2, column=1, sticky='w')

        self.t_var = tk.BooleanVar()
        self.t_check = tk.Checkbutton(self.options_frame, text='Test only, skip recompression (-t)', variable=self.t_var)
        self.t_check.grid(row=2, column=2, sticky='w')

        self.Q_var = tk.BooleanVar()
        self.Q_check = tk.Checkbutton(self.options_frame, text='Quick mode (-Q)', variable=self.Q_var, command=self.update_option_states)
        self.Q_check.grid(row=3, column=0, sticky='w')

        self.S_var = tk.BooleanVar()
        self.S_check = tk.Checkbutton(self.options_frame, text='Sequential mode (-S)', variable=self.S_var, command=self.update_option_states)
        self.S_check.grid(row=3, column=1, sticky='w')

        self.E_var = tk.BooleanVar()
        self.E_check = tk.Checkbutton(self.options_frame, text='Check ENCODER metadata (-E)', variable=self.E_var)
        self.E_check.grid(row=3, column=2, sticky='w')

        # Progress bar and label
        self.progress_frame = tk.Frame(self)
        self.progress_frame.grid(row=2, column=0, pady=10, padx=10, sticky='ew')
        self.progress_label = tk.Label(self.progress_frame, text='Ready', anchor='w', bg='#f0f0f0', relief='sunken', padx=5)
        self.progress_label.pack(fill='x', side='top')
        self.progress = ttk.Progressbar(self.progress_frame, orient='horizontal', mode='determinate', length=400)
        self.progress.pack(fill='x', side='top', pady=(2,0))

        # Run and log buttons
        btn_frame = tk.Frame(self)
        btn_frame.grid(row=3, column=0, pady=5, sticky='ew')
        btn_frame.grid_columnconfigure(0, weight=1)
        self.run_button = tk.Button(btn_frame, text='Run', command=self.run_flacr)
        self.run_button.grid(row=0, column=0, padx=5, sticky='w')
        self.cancel_button = tk.Button(btn_frame, text='Cancel', command=self.cancel_flacr, state='disabled')
        self.cancel_button.grid(row=0, column=1, padx=5, sticky='w')
        self.log_button = tk.Button(btn_frame, text='View Error Log', command=self.open_error_log)
        self.log_button.grid(row=0, column=2, padx=5, sticky='w')
        self.help_button = tk.Button(btn_frame, text='Help', command=self.show_help)
        self.help_button.grid(row=0, column=3, padx=5, sticky='w')
        self.copy_cmd_button = tk.Button(btn_frame, text='Copy CLI Command', command=self.copy_cli_command)
        self.copy_cmd_button.grid(row=0, column=4, padx=5, sticky='w')

        # Output box with tag for error highlighting
        self.output_text = tk.Text(self, height=15, width=80, state='normal', wrap='word')
        self.output_text.grid(row=4, column=0, padx=10, pady=5, sticky='nsew')
        self.output_text.tag_configure('error', foreground='red')
        self.output_text.tag_configure('warn', foreground='orange')
        self.output_text.tag_configure('bold', font=('TkDefaultFont', 10, 'bold'))
        self.output_text.tag_configure('skipped', foreground='blue')

        # Make output box expandable
        self.grid_rowconfigure(4, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def browse_dir(self):
        directory = filedialog.askdirectory(initialdir=self.dir_var.get())
        if directory:
            self.dir_var.set(directory)

    def run_flacr(self):
        if not self.check_dependencies():
            return
        if self.p_var.get() and not self.tqdm_installed():
            if not messagebox.askyesno('tqdm not installed', 'tqdm is required for progress bars. Continue anyway?'):
                return
        if (self.j_var.get() or self.S_var.get()):
            if not self.flac_supports_threads():
                messagebox.showwarning('flac version too old', 'flac >=1.5.0 is required for multi-threaded encoding (-j/-S).')
                return
        self.save_settings()
        self.run_button.config(state='disabled')
        self.cancel_button.config(state='normal')
        self.output_text.config(state='normal')
        self.output_text.delete(1.0, tk.END)
        self.output_text.insert(tk.END, 'Running flacr...\n', 'bold')
        self.output_text.insert(tk.END, 'Note: Timeouts are dynamic based on operation (5min-2hrs). GUI shows real-time status.\n', 'warn')
        self.output_text.config(state='disabled')
        self.progress['value'] = 0
        self.progress_label.config(text='Starting...')
        args = self.build_args()
        threading.Thread(target=self._run_flacr_thread, args=(args,), daemon=True).start()

    def cancel_flacr(self):
        """Cancel the running flacr process"""
        if self.process and self.process.poll() is None:
            try:
                self.append_output('\n[CANCELLED BY USER]\n', tag='error')
                self.process_active = False  # Signal threads to stop
                self._terminate_process_safely()
            except Exception as e:
                self.append_output(f'Error during cancellation: {e}\n', tag='error')
            finally:
                self.run_button.config(state='normal')
                self.cancel_button.config(state='disabled')

    def tqdm_installed(self):
        try:
            import tqdm
            return True
        except ImportError:
            return False

    def flac_supports_threads(self):
        flac_path = shutil.which('flac')
        if not flac_path:
            return False
        try:
            out = subprocess.check_output([flac_path, '--version'], encoding='utf-8', stderr=subprocess.STDOUT)
            m = re.search(r'flac (\d+)\.(\d+)\.(\d+)', out)
            if m:
                major, minor, patch = map(int, m.groups())
                return (major > 1) or (major == 1 and minor >= 5)
        except Exception:
            return False
        return False

    def build_args(self):
        args = [sys.executable, SCRIPT_PATH]
        if self.dir_var.get():
            args += ['-d', self.dir_var.get()]
        if self.j_var.get():
            args.append('-j')
        if self.l_var.get():
            args.append('-l')
        if self.m_var.get():
            args += ['-m', str(self.m_var.get())]
        if self.p_var.get():
            args.append('-p')
        if self.r_var.get():
            args.append('-r')
        if self.s_var.get():
            args.append('-s')
        if self.t_var.get():
            args.append('-t')
        if self.Q_var.get():
            args.append('-Q')
        if self.S_var.get():
            args.append('-S')
        if self.E_var.get():
            args.append('-E')
        return args

    def _run_flacr_thread(self, args):
        try:
            # Use a more robust subprocess approach for Windows
            self.output_queue = queue.Queue()
            self.process_active = True
            
            # Configure subprocess for Windows
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW
            
            # Start the subprocess with minimal buffering
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0,  # No buffering to prevent memory issues
                creationflags=creation_flags,
                universal_newlines=True
            )
            
            # Start output reading thread
            output_thread = threading.Thread(
                target=self._read_process_output,
                daemon=True
            )
            output_thread.start()
            
            # Process output from queue
            total_files = None
            processed = 0
            current_file = ''
            last_output_time = time.time()
            last_progress_time = time.time()
            current_operation = "Starting"
            
            # Dynamic timeout settings based on operation
            base_timeout = 300  # 5 minutes base timeout
            operation_timeouts = {
                'scanning': 600,      # 10 minutes for scanning large directories
                'checking': 1800,     # 30 minutes for checking files (metadata operations can be slow)
                'encoding': 3600,     # 1 hour for encoding (large files take time)
                'verifying': 1800,    # 30 minutes for verification
                'rsgain': 7200,       # 2 hours for replay gain calculation
                'default': 600        # 10 minutes default
            }
            
            while self.process_active:
                try:
                    # Check if process finished
                    if self.process and self.process.poll() is not None:
                        self.process_active = False
                        break
                    
                    # Get output from queue with timeout
                    try:
                        line = self.output_queue.get(timeout=0.5)
                        if line is None:  # End of output signal
                            break
                            
                        current_time = time.time()
                        last_output_time = current_time
                        
                        # Process the line
                        self.append_output(line)
                        
                        # Detect current operation and update status
                        operation_detected = self._detect_current_operation(line)
                        if operation_detected:
                            current_operation = operation_detected
                            last_progress_time = current_time  # Reset progress timeout on operation change
                        
                        # Extract total files count
                        if total_files is None:
                            summary_match = re.search(r'(\d+) flac files', line)
                            if summary_match:
                                total_files = int(summary_match.group(1))
                                self.progress['maximum'] = total_files
                                self.progress_label.config(text=f'Found {total_files} FLAC files')
                        
                        # Track file progress with comprehensive patterns
                        file_info = self._extract_file_info(line)
                        if file_info:
                            file_path, operation_type = file_info
                            current_file = file_path
                            
                            # Only increment for actual processing operations
                            if operation_type in ['processing', 'encoding', 'verifying']:
                                processed += 1
                            
                            last_progress_time = current_time
                            status_text = f'{operation_type.title()}: {os.path.basename(current_file)}'
                            self.update_progress(processed, total_files or processed, current_file, status_text)
                        
                        # Handle rsgain output specially
                        if self._is_rsgain_output(line):
                            current_operation = "rsgain"
                            last_progress_time = current_time
                            rsgain_status = self._parse_rsgain_output(line)
                            if rsgain_status:
                                self.progress_label.config(text=f'Replay Gain: {rsgain_status}')
                        
                    except queue.Empty:
                        # No output available, check timeouts
                        current_time = time.time()
                        
                        # Get appropriate timeout for current operation
                        current_timeout = operation_timeouts.get(current_operation.lower(), operation_timeouts['default'])
                        
                        time_since_output = current_time - last_output_time
                        time_since_progress = current_time - last_progress_time
                        
                        # Show what we're waiting for
                        if time_since_output > 30:  # After 30 seconds of no output
                            waiting_text = f'Waiting for {current_operation}'
                            if current_file:
                                waiting_text += f' on {os.path.basename(current_file)}'
                            self.progress_label.config(text=waiting_text + f' ({int(time_since_output)}s)')
                        
                        # Timeout based on current operation
                        if time_since_output > current_timeout:
                            self.append_output(f'\n[TIMEOUT] No output for {current_timeout//60} minutes during {current_operation}.\n', tag='error')
                            if current_file:
                                self.append_output(f'[TIMEOUT] Last file: {current_file}\n', tag='error')
                            self._terminate_process_safely()
                            break
                        
                        # Progress timeout warning (longer than output timeout)
                        if time_since_progress > current_timeout * 2:
                            self.append_output(f'\n[WARNING] No progress for {(current_timeout*2)//60} minutes on {current_operation}\n', tag='warn')
                            if current_file:
                                self.append_output(f'[WARNING] Current file: {current_file}\n', tag='warn')
                            last_progress_time = current_time  # Reset warning timer
                        
                        # Update GUI to keep it responsive
                        self.update_idletasks()
                
                except Exception as e:
                    self.append_output(f'Error processing output: {e}\n', tag='error')
                    break
            
            # Wait for process to complete
            if self.process:
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._terminate_process_safely()
                
                # Handle completion status
                self._handle_process_completion(total_files, processed, current_file)
            
        except Exception as e:
            self.append_output(f'Critical error in process thread: {e}\n', tag='error')
            self.progress_label.config(text='Error occurred')
        finally:
            self.process_active = False
            self.run_button.config(state='normal')
            self.cancel_button.config(state='disabled')
            if hasattr(self, 'process') and self.process:
                try:
                    if self.process.poll() is None:
                        self.process.terminate()
                except:
                    pass
            self.process = None

    def _read_process_output(self):
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
                        line = line.rstrip('\r\n') + '\n'
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
                if HAS_FCNTL and hasattr(os, 'O_NONBLOCK') and hasattr(stdout, 'fileno'):
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
                            remaining_lines.append(line.rstrip('\r\n') + '\n')
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
                if self.process and self.process.stdout and not self.process.stdout.closed:
                    # Don't close stdout here - let subprocess handle it
                    pass
            except Exception:
                pass

    def _detect_current_operation(self, line):
        """Detect what operation is currently being performed"""
        line_lower = line.lower()
        
        if 'scanning' in line_lower or 'searching' in line_lower:
            return 'scanning'
        elif 'checking' in line_lower and ('files' in line_lower or 'metadata' in line_lower):
            return 'checking'
        elif 'encoding' in line_lower or 'recompress' in line_lower:
            return 'encoding'
        elif 'verifying' in line_lower or 'testing' in line_lower:
            return 'verifying'
        elif 'rsgain' in line_lower or 'replay gain' in line_lower:
            return 'rsgain'
        elif 'calculating' in line_lower:
            return 'rsgain'
        
        return None

    def _extract_file_info(self, line):
        """Extract file information and operation type from output line"""
        patterns = [
            # Core processing patterns
            (r'Processing:\s*(.+\.flac)', 'processing'),
            (r'Verifying:\s*(.+\.flac)', 'verifying'),
            (r'Encoding:\s*(.+\.flac)', 'encoding'),
            (r'Checking:\s*(.+\.flac)', 'checking'),
            (r'Successfully processed:\s*(.+\.flac)', 'completed'),
            
            # File status patterns
            (r'Will re-encode:\s*(.+\.flac)', 'queued'),
            (r'Skipping (.+\.flac):', 'skipped'),
            (r'(.+\.flac): already encoded', 'skipped'),
            
            # Error patterns
            (r'Error processing (.+\.flac):', 'error'),
            (r'Verification error for (.+\.flac):', 'error'),
            
            # Generic file mention
            (r'([^\\/:*?"<>|\s]+\.flac)', 'mentioned')
        ]
        
        for pattern, operation_type in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                file_path = match.group(1).strip()
                # Clean up path - remove quotes and extra spaces
                file_path = file_path.strip('"\'')
                return file_path, operation_type
        
        return None

    def _is_rsgain_output(self, line):
        """Check if line is rsgain output"""
        rsgain_indicators = [
            'rsgain', 'replay gain', 'loudness', 'lufs', 'peak',
            'scanning', 'album gain', 'track gain'
        ]
        line_lower = line.lower()
        return any(indicator in line_lower for indicator in rsgain_indicators)

    def _parse_rsgain_output(self, line):
        """Parse rsgain output for status information"""
        line_lower = line.lower()
        
        # Look for progress indicators
        if 'scanning' in line_lower:
            # Extract file being scanned
            file_match = re.search(r'([^\\/:*?"<>|\s]+\.flac)', line, re.IGNORECASE)
            if file_match:
                return f'Scanning {os.path.basename(file_match.group(1))}'
            return 'Scanning files...'
        
        elif 'writing' in line_lower or 'updating' in line_lower:
            return 'Writing replay gain tags...'
        
        elif 'album' in line_lower and 'gain' in line_lower:
            return 'Calculating album gain...'
        
        elif 'track' in line_lower and 'gain' in line_lower:
            return 'Calculating track gain...'
        
        elif 'complete' in line_lower or 'done' in line_lower:
            return 'Replay gain calculation complete'
        
        # Look for progress numbers
        progress_match = re.search(r'(\d+)/(\d+)', line)
        if progress_match:
            current, total = progress_match.groups()
            return f'Progress: {current}/{total}'
        
        return None

    def _terminate_process_safely(self):
        """Safely terminate the process using Windows-appropriate methods"""
        if not self.process or self.process.poll() is not None:
            return
        
        self.process_active = False  # Signal threads to stop
        
        try:
            if sys.platform == "win32":
                # On Windows, try terminate first
                self.process.terminate()
                self.append_output('[TERMINATING] Sending terminate signal...\n', tag='warn')
                
                # Wait a bit for graceful termination
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't terminate gracefully
                    self.process.kill()
                    self.append_output('[FORCE KILLED] Process force-killed\n', tag='error')
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass  # Process might be zombie now
            else:
                # Unix-like systems
                self.process.terminate()
                time.sleep(2)
                if self.process.poll() is None:
                    self.process.kill()
        except Exception as e:
            self.append_output(f'Error during process termination: {e}\n', tag='error')
        finally:
            # Ensure process handle is cleaned up
            try:
                if self.process and self.process.poll() is None:
                    self.process.kill()
            except:
                pass

    def _read_remaining_output(self):
        """Read any remaining output from the process - simplified for new approach"""
        # With the queue-based approach, this is handled by the output thread
        pass

    def _handle_process_completion(self, total_files, processed, current_file):
        """Handle the final process completion status"""
        if not self.process:
            return
            
        returncode = self.process.returncode
        
        if returncode == 0:
            self.update_progress(total_files or processed, total_files or processed, current_file)
            self.progress_label.config(text='Completed successfully')
            self.append_output('Done.\n', tag='bold')
        elif returncode in [-15, -9, 1]:  # SIGTERM, SIGKILL, or CTRL+C
            self.progress_label.config(text='Cancelled or interrupted')
            self.append_output('Process was cancelled or interrupted.\n', tag='warn')
        elif returncode == -1073741510:  # Windows CTRL+C
            self.progress_label.config(text='Cancelled by user')
            self.append_output('Process was cancelled by user.\n', tag='warn')
        else:
            self.progress_label.config(text=f'Failed with exit code {returncode}')
            self.append_output(f'Process exited with code {returncode}.\n', tag='error')

    def append_output(self, text, tag=None):
        # Schedule GUI update in main thread to prevent memory corruption
        self.after_idle(self._append_output_safe, text, tag)

    def _append_output_safe(self, text, tag=None):
        try:
            self.output_text.config(state='normal')
            
            # Auto-truncate log if it gets too long
            current_lines = int(self.output_text.index('end-1c').split('.')[0])
            if current_lines > self.max_log_lines:
                # Remove first 200 lines to prevent constant truncation
                self.output_text.delete('1.0', '201.0')
                self.output_text.insert('1.0', '[... earlier output truncated ...]\n', 'warn')
            
            # Highlight errors/warnings/skipped
            if tag is None:
                if text.startswith('SKIPPED_FLAC:'):
                    tag = 'skipped'
                elif re.search(r'error|failed|exception|not on PATH|locked|manual replacement', text, re.IGNORECASE):
                    tag = 'error'
                elif re.search(r'warn|skipping|cannot|missing', text, re.IGNORECASE):
                    tag = 'warn'
            
            self.output_text.insert(tk.END, text, tag)
            self.output_text.see(tk.END)
            self.output_text.config(state='disabled')
        except Exception as e:
            # Fallback: just print to console if GUI update fails
            print(f"GUI update error: {e}")
            print(f"Text: {text}")

    def update_progress(self, value, maximum, current_file=None, status_text=None):
        # Schedule progress update in main thread
        self.after_idle(self._update_progress_safe, value, maximum, current_file, status_text)

    def _update_progress_safe(self, value, maximum, current_file=None, status_text=None):
        try:
            self.progress['maximum'] = maximum
            self.progress['value'] = value
            
            if status_text:
                # Use provided status text
                if maximum > 0:
                    percentage = (value / maximum * 100)
                    self.progress_label.config(text=f'{status_text} ({value}/{maximum} - {percentage:.1f}%)')
                else:
                    self.progress_label.config(text=f'{status_text} ({value} files)')
            elif current_file:
                # Fallback to file-based status
                display_file = os.path.basename(current_file)
                percentage = (value / maximum * 100) if maximum > 0 else 0
                self.progress_label.config(text=f'Processing: {display_file} ({value}/{maximum} - {percentage:.1f}%)')
            elif maximum > 0:
                # Generic progress
                percentage = (value / maximum * 100)
                self.progress_label.config(text=f'Progress: {value}/{maximum} files ({percentage:.1f}%)')
            else:
                # Unknown progress
                self.progress_label.config(text=f'Processing... ({value} files)')
        except Exception as e:
            print(f"Progress update error: {e}")

    def check_dependencies(self):
        missing = []
        if not shutil.which('flac'):
            missing.append('flac')
        if not shutil.which('metaflac'):
            missing.append('metaflac')
        if self.r_var.get() and not shutil.which('rsgain'):
            missing.append('rsgain')
        if missing:
            messagebox.showerror('Missing Dependencies', f'The following tools are missing: {", ".join(missing)}.\nPlease install them and try again.')
            return False
        return True

    def open_error_log(self):
        if not os.path.exists(ERROR_LOG_PATH):
            messagebox.showinfo('Error Log', 'No error log found.')
            return
        log_win = tk.Toplevel(self)
        log_win.title('flacr_error.log')
        log_win.geometry('700x400')
        text = tk.Text(log_win, wrap='word')
        text.pack(expand=True, fill='both')
        with open(ERROR_LOG_PATH, encoding='utf8') as f:
            log_content = f.read()
        text.insert('1.0', log_content)
        text.config(state='disabled')

    def show_help(self):
        help_text = (
            'flacr - FLAC Recompressor GUI\n\n'
            'Options:\n'
            '-d: Directory to scan for .flac files.\n'
            '-j: flac >=1.5.0: Encode 1 file at a time with multi-threading (threadcount via -m) instead of encoding multiple files concurrently.\n'
            '-l: Log errors to flacr.log.\n'
            '-m: Number of threads for conversion and replay gain calculation.\n'
            '-p: Show progress bars (requires tqdm).\n'
            '-r: Calculate replay gain (requires rsgain).\n'
            '-s: Only scan the current folder.\n'
            '-t: Test only, skip recompression.\n'
            '-Q: Quick mode: -r -p and -m with all available threads.\n'
            '-S: Sequential mode: -j -r -p and -m 4.\n'
            '-E: Check and fix ENCODER metadata tags.\n\n'
            'Common examples:\n'
            'Test flac files for errors (4 threads):\n'
            '  flacr.py -t -m 4\n'
            'Recompress flac files, no replay gain (4 threads):\n'
            '  flacr.py -m 4\n'
            'Recompress and calculate replay gain (all threads, progress):\n'
            '  flacr.py -Q\n'
            'Sequential mode (4 threads, progress):\n'
            '  flacr.py -S\n'
            'Check and fix ENCODER metadata:\n'
            '  flacr.py -E\n'
            'With directory:\n'
            '  flacr.py -rlp -m 4 -d "D:/Test"\n\n'
            'Documentation:\n'
            'https://github.com/AverageHoarder/flacr\n'
            'https://github.com/complexlogic/rsgain/releases\n'
            'https://xiph.org/flac/download.html\n'
            'https://github.com/tqdm/tqdm\n'
        )
        messagebox.showinfo('Help', help_text)

    def copy_cli_command(self):
        args = self.build_args()
        # Remove sys.executable and script path for CLI copy
        cli_args = args[2:] if args[0].endswith('python.exe') else args[1:]
        cmd = f'python flacr.py {" ".join(map(str, cli_args))}'
        self.clipboard_clear()
        self.clipboard_append(cmd)
        messagebox.showinfo('CLI Command', f'Copied to clipboard:\n{cmd}')

    def update_option_states(self):
        # Quick mode: -Q sets -m to max, -r, -p, disables -S
        if self.Q_var.get():
            self.S_var.set(False)
            self.r_var.set(True)
            self.p_var.set(True)
            self.m_var.set(os.cpu_count())
            self.m_spin.config(state='disabled')
            self.r_check.config(state='disabled')
            self.p_check.config(state='disabled')
            self.S_check.config(state='disabled')
        else:
            self.m_spin.config(state='normal')
            self.r_check.config(state='normal')
            self.p_check.config(state='normal')
            self.S_check.config(state='normal')

        # Sequential mode: -S sets -m 4, -j, -r, -p, disables -Q
        if self.S_var.get():
            self.Q_var.set(False)
            self.r_var.set(True)
            self.p_var.set(True)
            self.j_var.set(True)
            self.m_var.set(4 if os.cpu_count() >= 4 else os.cpu_count())
            self.m_spin.config(state='disabled')
            self.r_check.config(state='disabled')
            self.p_check.config(state='disabled')
            self.j_check.config(state='disabled')
            self.Q_check.config(state='disabled')
        else:
            if not self.Q_var.get():
                self.m_spin.config(state='normal')
                self.r_check.config(state='normal')
                self.p_check.config(state='normal')
            self.j_check.config(state='normal')
            self.Q_check.config(state='normal')

    def save_settings(self):
        # Overwrite the config file from scratch to avoid any duplicate section or option errors
        config = configparser.ConfigParser()
        config.clear()  # Ensure config is empty
        config.add_section('main')
        config.set('main', 'directory', self.dir_var.get())
        config.set('main', 'j', str(self.j_var.get()))
        config.set('main', 'l', str(self.l_var.get()))
        config.set('main', 'm', str(self.m_var.get()))
        config.set('main', 'p', str(self.p_var.get()))
        config.set('main', 'r', str(self.r_var.get()))
        config.set('main', 's', str(self.s_var.get()))
        config.set('main', 't', str(self.t_var.get()))
        config.set('main', 'Q', str(self.Q_var.get()))
        config.set('main', 'S', str(self.S_var.get()))
        config.set('main', 'E', str(self.E_var.get()))
        with open(CONFIG_PATH, 'w') as f:
            config.write(f)

    def load_settings(self):
        config = configparser.ConfigParser()
        if os.path.exists(CONFIG_PATH):
            config.read(CONFIG_PATH)
            if config.has_section('main'):
                self.dir_var.set(config.get('main', 'directory', fallback=os.getcwd()))
                self.j_var.set(config.getboolean('main', 'j', fallback=False))
                self.l_var.set(config.getboolean('main', 'l', fallback=False))
                self.m_var.set(config.getint('main', 'm', fallback=1))
                self.p_var.set(config.getboolean('main', 'p', fallback=False))
                self.r_var.set(config.getboolean('main', 'r', fallback=False))
                self.s_var.set(config.getboolean('main', 's', fallback=False))
                self.t_var.set(config.getboolean('main', 't', fallback=False))
                self.Q_var.set(config.getboolean('main', 'Q', fallback=False))
                self.S_var.set(config.getboolean('main', 'S', fallback=False))
                self.E_var.set(config.getboolean('main', 'E', fallback=False))
                self.update_option_states()

    def on_close(self):
        # Ensure any running process is properly terminated
        if hasattr(self, 'process') and self.process and self.process.poll() is None:
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

if __name__ == '__main__':
    app = FlacrGUI()
    app.mainloop()
