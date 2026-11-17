"""Audio Cutter: a small desktop interface for yt-dlp and FFmpeg."""
import importlib.util
import queue
import shutil
import subprocess
import sys
import threading
import time
import tempfile
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse


def timestamp(value):
    parts = value.strip().split(':')
    if not 1 <= len(parts) <= 3:
        raise ValueError('Use seconds, MM:SS, or HH:MM:SS.')
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        raise ValueError('Time values must contain whole numbers.') from None
    if any(n < 0 for n in numbers) or any(n >= 60 for n in numbers[1:]):
        raise ValueError('Minutes and seconds after a colon must be between 00 and 59.')
    return sum(n * 60 ** i for i, n in enumerate(reversed(numbers)))


def validate(url, rows):
    parsed = urlparse(url.strip())
    if parsed.scheme not in ('https', 'http') or parsed.hostname not in (
        'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'
    ):
        raise ValueError('Paste a YouTube video link.')
    ranges = []
    for index, (start, end) in enumerate(rows, 1):
        try:
            a, b = timestamp(start), timestamp(end)
            if b <= a:
                raise ValueError('The end must be later than the start.')
        except ValueError as exc:
            raise ValueError(f'Range {index}: {exc}') from None
        ranges.append((a, b))
    if not ranges:
        raise ValueError('Add at least one time range.')
    return ranges


def failure_message(output):
    text = output.lower()
    if '429' in text or 'confirm' in text and 'bot' in text:
        return ('YouTube blocked this request. Open the video in your browser, complete any '
                'sign-in or verification, then select a YouTube cookies file and retry. '
                'If rate limiting continues, wait before trying again.')
    if 'cookie' in text and ('decrypt' in text or 'database' in text):
        return 'Could not read the cookies. Export a fresh YouTube cookies file and select it.'
    return 'Export failed. See the log for details; earlier clips remain saved.'


class App:
    def __init__(self, root):
        self.root = root
        root.title('Audio Cutter')
        root.geometry('820x790')
        root.minsize(640, 540)
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.process = None
        self.busy = False
        self.started_at = None
        self.activity_at = None
        self.stage = 'Ready'
        self.rows = []
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#f4f6fa')
        style.configure('TLabel', background='#f4f6fa', font=('Segoe UI', 10))
        style.configure('TButton', padding=7, font=('Segoe UI', 10))
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Audio Cutter', font=('Segoe UI', 24, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Keep the moments you want. Preserve the original audio.').pack(anchor='w', pady=(2, 20))
        ttk.Label(frame, text='YouTube video link').pack(anchor='w')
        self.url = ttk.Entry(frame)
        self.url.pack(fill='x', pady=(5, 16))
        ttk.Label(frame, text='Time ranges · MM:SS or HH:MM:SS').pack(anchor='w')
        self.range_frame = ttk.Frame(frame)
        self.range_frame.pack(fill='x', pady=5)
        self.add_range('56:22', '59:33')
        ttk.Button(frame, text='+ Add range', command=self.add_range).pack(anchor='w', pady=(2, 14))
        ttk.Label(frame, text='Save clips to').pack(anchor='w')
        folder_row = ttk.Frame(frame)
        folder_row.pack(fill='x', pady=5)
        self.folder = tk.StringVar(value=str(Path.home() / 'Music' / 'Audio Cutter'))
        ttk.Entry(folder_row, textvariable=self.folder).pack(side='left', fill='x', expand=True)
        ttk.Button(folder_row, text='Browse…', command=self.browse).pack(side='left', padx=(8, 0))
        ttk.Label(frame, text='YouTube cookies file (optional, for sign-in checks)').pack(anchor='w', pady=(12, 0))
        cookie_row = ttk.Frame(frame)
        cookie_row.pack(fill='x', pady=5)
        self.cookies = tk.StringVar()
        ttk.Entry(cookie_row, textvariable=self.cookies).pack(side='left', fill='x', expand=True)
        ttk.Button(cookie_row, text='Select…', command=self.select_cookies).pack(side='left', padx=(8, 0))
        ttk.Button(cookie_row, text='Clear', command=lambda: self.cookies.set('')).pack(side='left', padx=4)
        ttk.Label(frame, text='Use a Netscape cookies.txt file. Keep it private; it contains sign-in data.').pack(anchor='w')
        ttk.Label(frame, text='Original audio • Separate file for each range • No re-encoding').pack(anchor='w', pady=(12, 4))
        ttk.Label(frame, text='Cut points may vary slightly at audio-packet boundaries.').pack(anchor='w')
        self.reliable = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text='Download audio once, then cut locally (more reliable; uses more data)',
                        variable=self.reliable).pack(anchor='w', pady=6)
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=16)
        self.export = ttk.Button(actions, text='Export audio clips', command=self.start)
        self.export.pack(side='left')
        self.cancel = ttk.Button(actions, text='Cancel', command=self.stop, state='disabled')
        self.cancel.pack(side='left', padx=8)
        self.progress = ttk.Progressbar(frame, mode='indeterminate')
        self.progress.pack(fill='x')
        self.status = tk.StringVar(value='Ready')
        ttk.Label(frame, textvariable=self.status, wraplength=710).pack(anchor='w', pady=8)
        self.log = tk.Text(frame, height=7, wrap='word', font=('Consolas', 9), state='disabled')
        self.log.pack(fill='both', expand=True)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def add_range(self, start='', end=''):
        if self.busy:
            return
        row = ttk.Frame(self.range_frame)
        row.pack(fill='x', pady=3)
        a, b = ttk.Entry(row, width=16), ttk.Entry(row, width=16)
        a.insert(0, start)
        b.insert(0, end)
        a.pack(side='left')
        ttk.Label(row, text='  to  ').pack(side='left')
        b.pack(side='left')
        entry = (row, a, b)
        def remove():
            if not self.busy:
                self.rows.remove(entry)
                row.destroy()
        ttk.Button(row, text='Remove', command=remove).pack(side='left', padx=8)
        self.rows.append(entry)

    def browse(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder.set(folder)

    def select_cookies(self):
        path = filedialog.askopenfilename(title='Select YouTube cookies file',
                                          filetypes=[('Text files', '*.txt'), ('All files', '*.*')])
        if path:
            self.cookies.set(path)

    def start(self):
        try:
            url = self.url.get().strip()
            ranges = validate(url, [(a.get(), b.get()) for _, a, b in self.rows])
            if not self.folder.get().strip():
                raise ValueError('Choose an output folder.')
            cookies = self.cookies.get().strip()
            if cookies:
                with open(cookies, encoding='utf-8-sig') as cookie_file:
                    header = cookie_file.readline().strip()
                if header not in ('# HTTP Cookie File', '# Netscape HTTP Cookie File'):
                    raise ValueError('Select a cookies file in Netscape cookies.txt format.')
            if importlib.util.find_spec('yt_dlp') is None:
                raise ValueError('Install the required downloader first. See README.md for setup.')
            if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
                raise ValueError('FFmpeg and FFprobe must be installed and available on PATH.')
            destination = Path(self.folder.get()).expanduser() / datetime.now().strftime('Clips-%Y%m%d-%H%M%S-%f')
            destination.mkdir(parents=True)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Cannot export', str(exc))
            return
        self.busy = True
        self.started_at = self.activity_at = time.monotonic()
        self.stage = 'Starting export…'
        self.cancelled.clear()
        self.export.configure(state='disabled')
        self.cancel.configure(state='normal')
        self.progress.start()
        threading.Thread(target=self.work, args=(url, ranges, destination, cookies, self.reliable.get()), daemon=True).start()

    def work(self, url, ranges, destination, cookies='', reliable=True):
        temporary = None
        try:
            if reliable:
                temporary = tempfile.TemporaryDirectory(prefix='audio-cutter-')
            jobs = ([(0, (0, 0))] if reliable else []) + list(enumerate(ranges, 1))
            for i, (start, end) in jobs:
                if self.cancelled.is_set():
                    break
                self.events.put(('status', f'Exporting clip {i} of {len(ranges)}…'))
                command = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist',
                           '--newline', '--no-colors', '-f', 'bestaudio',
                           '--socket-timeout', '20', '--retries', '2',
                           '--extractor-retries', '2', '--fragment-retries', '2',
                           '--downloader-args', 'ffmpeg_i:-rw_timeout 20000000',
                           '--download-sections', f'*{start}-{end}',
                           '-o', str(destination / f'{i:02d} - %(title).120B [{start}-{end}].%(ext)s'),
                           '--windows-filenames', '--', url]
                if shutil.which('node') and not shutil.which('deno'):
                    command[3:3] = ['--js-runtimes', 'node']
                command[3:3] = ['--encoding', 'utf-8']
                if cookies:
                    command[3:3] = ['--cookies', cookies]
                if reliable and i == 0:
                    self.events.put(('status', 'Downloading source audio once before cutting clips…'))
                    section_index = command.index('--download-sections')
                    del command[section_index:section_index + 2]
                    command[command.index('-o') + 1] = str(Path(temporary.name) / 'source.%(ext)s')
                elif reliable:
                    sources = [p for p in Path(temporary.name).glob('source.*')
                               if p.suffix not in ('.part', '.ytdl')]
                    if len(sources) != 1:
                        raise RuntimeError('The downloaded audio file could not be identified.')
                    source = sources[0]
                    command = [shutil.which('ffmpeg'), '-hide_banner', '-nostdin', '-n',
                               '-i', str(source), '-ss', str(start), '-t', str(end - start),
                               '-map', '0:a:0', '-c:a', 'copy',
                               str(destination / f'{i:02d} - clip [{start}-{end}]{source.suffix}')]
                recent_output = []
                output = queue.Queue()
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                text=True, encoding='utf-8', errors='replace',
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if self.cancelled.is_set():
                    self.terminate()
                process = self.process
                def read_output(process=process, output=output):
                    try:
                        for line in process.stdout:
                            output.put(line)
                    finally:
                        process.stdout.close()
                        output.put(None)
                threading.Thread(target=read_output, daemon=True).start()
                last_output = time.monotonic()
                stalled = False
                while True:
                    try:
                        line = output.get(timeout=1)
                    except queue.Empty:
                        if self.cancelled.is_set():
                            self.terminate()
                        elif time.monotonic() - last_output > 120:
                            stalled = True
                            self.terminate()
                        if process.poll() is not None:
                            break
                        continue
                    if line is None:
                        break
                    last_output = time.monotonic()
                    recent_output.append(line)
                    recent_output = recent_output[-80:]
                    self.events.put(('log', line.rstrip()))
                    label = 'Downloading source audio' if i == 0 else f'Clip {i}/{len(ranges)}'
                    self.events.put(('activity', f'{label}: {line.strip()[:160]}'))
                code = self.process.wait()
                self.process = None
                if stalled and not self.cancelled.is_set():
                    raise RuntimeError('Stopped: the downloader sent no updates for 2 minutes. '
                                       'Check the connection and activity log before retrying.')
                if code and not self.cancelled.is_set():
                    raise RuntimeError(failure_message(''.join(recent_output)))
            self.events.put(('status', 'Cancelled. Partial files may remain.' if self.cancelled.is_set()
                             else f'Finished! Clips saved to {destination}'))
        except Exception as exc:
            self.events.put(('status', str(exc)))
        finally:
            if temporary:
                try:
                    temporary.cleanup()
                except OSError:
                    self.events.put(('log', 'Temporary audio cleanup failed; files may remain in your temp folder.'))
            self.events.put(('done', ''))

    def terminate(self):
        process = self.process
        if process and process.poll() is None:
            # Stop FFmpeg children as well as the downloader on Windows.
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def stop(self):
        self.cancelled.set()
        threading.Thread(target=self.terminate, daemon=True).start()

    def close(self):
        if self.busy:
            self.stop()
        self.root.destroy()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'status':
                    self.stage = value
                    self.status.set(value)
                elif kind == 'activity':
                    self.stage = value
                    self.activity_at = time.monotonic()
                elif kind == 'log':
                    self.log.configure(state='normal')
                    self.log.insert('end', value + '\n')
                    self.log.see('end')
                    self.log.configure(state='disabled')
                elif kind == 'done':
                    self.busy = False
                    self.progress.stop()
                    self.export.configure(state='normal')
                    self.cancel.configure(state='disabled')
        except queue.Empty:
            pass
        if self.busy and self.started_at:
            elapsed = int(time.monotonic() - self.started_at)
            quiet = int(time.monotonic() - self.activity_at)
            self.status.set(f'{self.stage}\nElapsed {elapsed // 60}:{elapsed % 60:02d}'
                            + (f' • No update for {quiet}s' if quiet >= 15 else ''))
        self.root.after(100, self.poll)


if __name__ == '__main__':
    App(tk.Tk())
    tk.mainloop()
