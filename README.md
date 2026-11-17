# Audio Cutter

A Windows desktop app for exporting multiple audio ranges from a YouTube video.
The default and currently supported output is the best available original audio
stream, without re-encoding. Depending on the source, files may be WebM or M4A.
Each range is saved separately in a unique export folder.

The default reliable mode downloads the complete audio stream once to a temporary
folder, then cuts all clips locally without re-encoding. This uses more bandwidth
and temporary disk space, but avoids remote seeking stalls and repeated extraction
for each range. Uncheck the reliable mode to download sections directly instead.
Network operations have bounded retries and timeouts. A downloader that produces
no output for two minutes is stopped. The status shows elapsed time and latest
activity; the progress bar indicates activity, not a percentage.

## Setup

Requires Python 3.10 or newer with Tkinter, FFmpeg (including FFprobe) on PATH,
and yt-dlp. Install the downloader from this folder:

```
python -m pip install -U -r requirements.txt
```

Current YouTube support may also require a JavaScript runtime such as Deno.
See the official setup documentation: https://github.com/yt-dlp/yt-dlp#installation
and https://github.com/yt-dlp/yt-dlp/wiki/EJS.

Double-click **Start Audio Cutter.bat** to launch. Paste a link, enter ranges in
seconds, MM:SS or HH:MM:SS, select a folder, and export. End times must follow
start times. Keep ranges within the video duration; unavailable or restricted
videos and ranges may fail, with details in the activity log.

The app uses yt-dlp's section downloader and FFmpeg stream copying. Cut boundaries
can vary slightly because preserving encoded audio requires cutting on packet
boundaries. It does not promise sample-exact cuts. Cancellation stops the process
tree; completed clips and partial downloads remain in the output folder.

## YouTube sign-in checks / HTTP 429

Open the video in your browser on the same connection and complete any sign-in
or verification YouTube requests. Export YouTube cookies in Netscape cookies.txt
format, then choose that file using **Select…** in the app. Cookie contents are
not shown in the app log. yt-dlp may update the selected cookie file during use.
Keep this file private because it contains sign-in data.

Follow the official YouTube cookie export steps (including the private-window
instructions to avoid cookie rotation):
https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies

Cookies do not guarantee access. If HTTP 429 continues, wait before retrying;
repeated retries can prolong the block. No automatic retry loop is used.

## Development checks

```
python -m unittest discover -s tests
```
