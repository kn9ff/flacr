# --- Improved GUI for flacr.py ---
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import subprocess
import sys
import os
import shutil
import configparser
import re

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), 'flacr.py')
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.flacr_gui.ini')
ERROR_LOG_PATH = os.path.join(os.path.dirname(__file__), 'flacr_error.log')

class FlacrGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('flacr - FLAC Recompressor GUI')
        self.geometry('700x650')
        self.minsize(600, 500)
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

        # Progress bar
        self.progress = ttk.Progressbar(self, orient='horizontal', mode='determinate', length=400)
        self.progress.grid(row=2, column=0, pady=10, padx=10, sticky='ew')

        # Run and log buttons
        btn_frame = tk.Frame(self)
        btn_frame.grid(row=3, column=0, pady=5, sticky='ew')
        btn_frame.grid_columnconfigure(0, weight=1)
        self.run_button = tk.Button(btn_frame, text='Run', command=self.run_flacr)
        self.run_button.grid(row=0, column=0, padx=5, sticky='w')
        self.log_button = tk.Button(btn_frame, text='View Error Log', command=self.open_error_log)
        self.log_button.grid(row=0, column=1, padx=5, sticky='w')
        self.help_button = tk.Button(btn_frame, text='Help', command=self.show_help)
        self.help_button.grid(row=0, column=2, padx=5, sticky='w')

        # Output box with tag for error highlighting
        self.output_text = tk.Text(self, height=15, width=80, state='disabled', wrap='word')
        self.output_text.grid(row=4, column=0, padx=10, pady=5, sticky='nsew')
        self.output_text.tag_configure('error', foreground='red')
        self.output_text.tag_configure('warn', foreground='orange')
        self.output_text.tag_configure('bold', font=('TkDefaultFont', 10, 'bold'))

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
        self.save_settings()
        self.run_button.config(state='disabled')
        self.output_text.config(state='normal')
        self.output_text.delete(1.0, tk.END)
        self.output_text.insert(tk.END, 'Running flacr...\n', 'bold')
        self.output_text.config(state='disabled')
        self.progress['value'] = 0
        args = self.build_args()
        threading.Thread(target=self._run_flacr_thread, args=(args,), daemon=True).start()

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
        return args

    def _run_flacr_thread(self, args):
        try:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            total_files = None
            processed = 0
            for line in process.stdout:
                self.append_output(line)
                # Progress bar update: parse tqdm output
                # Look for lines like: "encoding:  23%|██▎       | 7/30 [00:01<00:04,  5.00 files/s]"
                tqdm_match = re.search(r'(encoding|verifying|searching).*\|\s*(\d+)/(\d+)', line)
                if tqdm_match:
                    processed = int(tqdm_match.group(2))
                    total_files = int(tqdm_match.group(3))
                    self.update_progress(processed, total_files)
            process.wait()
            self.update_progress(total_files or 0, total_files or 1)
            if process.returncode == 0:
                self.append_output('Done.\n', tag='bold')
            else:
                self.append_output(f'Process exited with code {process.returncode}.\n', tag='error')
        except Exception as e:
            self.append_output(f'Error: {e}\n', tag='error')
        finally:
            self.run_button.config(state='normal')

    def append_output(self, text, tag=None):
        self.output_text.config(state='normal')
        # Highlight errors/warnings
        if tag is None:
            if re.search(r'error|failed|exception|not on PATH|locked|manual replacement', text, re.IGNORECASE):
                tag = 'error'
            elif re.search(r'warn|skipping|cannot|missing', text, re.IGNORECASE):
                tag = 'warn'
        self.output_text.insert(tk.END, text, tag)
        self.output_text.see(tk.END)
        self.output_text.config(state='disabled')

    def update_progress(self, value, maximum):
        self.progress['maximum'] = maximum
        self.progress['value'] = value
        self.update_idletasks()

    def check_dependencies(self):
        missing = []
        if not shutil.which('flac'):
            missing.append('flac')
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
            '-j: Encode 1 file at a time with multi-threading.\n'
            '-l: Log errors to flacr.log.\n'
            '-m: Number of threads for conversion.\n'
            '-p: Show progress bars.\n'
            '-r: Calculate replay gain.\n'
            '-s: Only scan the current folder.\n'
            '-t: Test only, skip recompression.\n'
            '-Q: Quick mode.\n'
            '-S: Sequential mode.\n\n'
            'Documentation:\n'
            'https://github.com/complexlogic/rsgain/releases\n'
            'https://xiph.org/flac/download.html\n'
        )
        messagebox.showinfo('Help', help_text)

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
                self.update_option_states()

    def on_close(self):
        self.save_settings()
        self.destroy()

if __name__ == '__main__':
    app = FlacrGUI()
    app.mainloop()
