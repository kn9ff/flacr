import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import subprocess
import sys
import os
import shutil

# Path to the CLI script
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), 'flacr.py')

class FlacrGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('flacr - FLAC Recompressor GUI')
        self.geometry('600x600')
        self.resizable(False, False)
        self.create_widgets()

    def create_widgets(self):
        # Directory selection
        self.dir_label = tk.Label(self, text='Directory:')
        self.dir_label.pack(anchor='w', padx=10, pady=(10, 0))
        self.dir_var = tk.StringVar(value=os.getcwd())
        self.dir_entry = tk.Entry(self, textvariable=self.dir_var, width=50)
        self.dir_entry.pack(anchor='w', padx=10)
        self.dir_button = tk.Button(self, text='Browse...', command=self.browse_dir)
        self.dir_button.pack(anchor='w', padx=10, pady=(0, 10))

        # Options
        self.options_frame = tk.LabelFrame(self, text='Options')
        self.options_frame.pack(fill='x', padx=10, pady=5)

        self.j_var = tk.BooleanVar()
        self.j_check = tk.Checkbutton(self.options_frame, text='Encode 1 file at a time with multi-threading (-j)', variable=self.j_var)
        self.j_check.pack(anchor='w')

        self.l_var = tk.BooleanVar()
        self.l_check = tk.Checkbutton(self.options_frame, text='Log errors to flacr.log (-l)', variable=self.l_var)
        self.l_check.pack(anchor='w')

        self.m_label = tk.Label(self.options_frame, text='Thread count (-m):')
        self.m_label.pack(anchor='w')
        self.m_var = tk.IntVar(value=1)
        self.m_spin = tk.Spinbox(self.options_frame, from_=1, to=os.cpu_count(), textvariable=self.m_var, width=5)
        self.m_spin.pack(anchor='w')

        self.p_var = tk.BooleanVar()
        self.p_check = tk.Checkbutton(self.options_frame, text='Show progress bars (-p)', variable=self.p_var)
        self.p_check.pack(anchor='w')

        self.r_var = tk.BooleanVar()
        self.r_check = tk.Checkbutton(self.options_frame, text='Calculate replay gain (-r)', variable=self.r_var)
        self.r_check.pack(anchor='w')

        self.s_var = tk.BooleanVar()
        self.s_check = tk.Checkbutton(self.options_frame, text='Only scan current folder (-s)', variable=self.s_var)
        self.s_check.pack(anchor='w')

        self.t_var = tk.BooleanVar()
        self.t_check = tk.Checkbutton(self.options_frame, text='Test only, skip recompression (-t)', variable=self.t_var)
        self.t_check.pack(anchor='w')

        self.Q_var = tk.BooleanVar()
        self.Q_check = tk.Checkbutton(self.options_frame, text='Quick mode (-Q)', variable=self.Q_var)
        self.Q_check.pack(anchor='w')

        self.S_var = tk.BooleanVar()
        self.S_check = tk.Checkbutton(self.options_frame, text='Sequential mode (-S)', variable=self.S_var)
        self.S_check.pack(anchor='w')

        # Progress bar
        self.progress = ttk.Progressbar(self, orient='horizontal', mode='determinate', length=400)
        self.progress.pack(pady=10)

        # Run button
        self.run_button = tk.Button(self, text='Run', command=self.run_flacr)
        self.run_button.pack(pady=10)

        # Output box
        self.output_text = tk.Text(self, height=12, width=70, state='disabled')
        self.output_text.pack(padx=10, pady=5)

        # Help button
        self.help_button = tk.Button(self, text='Help', command=self.show_help)
        self.help_button.pack(side='left', padx=10, pady=10)

    def browse_dir(self):
        directory = filedialog.askdirectory(initialdir=self.dir_var.get())
        if directory:
            self.dir_var.set(directory)

    def run_flacr(self):
        if not self.check_dependencies():
            return
        self.run_button.config(state='disabled')
        self.output_text.config(state='normal')
        self.output_text.delete(1.0, tk.END)
        self.output_text.insert(tk.END, 'Running flacr...\n')
        self.output_text.config(state='disabled')
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
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                self.append_output(line)
            process.wait()
            if process.returncode == 0:
                self.append_output('Done.\n')
            else:
                self.append_output(f'Process exited with code {process.returncode}.\n')
        except Exception as e:
            self.append_output(f'Error: {e}\n')
        finally:
            self.run_button.config(state='normal')

    def append_output(self, text):
        self.output_text.config(state='normal')
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)
        self.output_text.config(state='disabled')

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
            '-S: Sequential mode.\n'
        )
        messagebox.showinfo('Help', help_text)

if __name__ == '__main__':
    app = FlacrGUI()
    app.mainloop()
