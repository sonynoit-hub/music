"""Download the audio of a YouTube, Instagram or TikTok post as WAV bytes."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlparse

ALLOWED_HOSTS = ('youtube.com', 'youtu.be', 'instagram.com', 'tiktok.com')
MAX_SECONDS = 20 * 60
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024


class LinkAudioError(ValueError):
    pass


def check_link(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('http', 'https') or not any(host == h or host.endswith('.' + h) for h in ALLOWED_HOSTS):
        raise LinkAudioError('Paste a YouTube, Instagram or TikTok link.')
    return url


def download_audio(url: str) -> tuple[bytes, str]:
    """Return (wav_bytes, title) for a single post; playlists use only the linked item."""
    url = check_link(url)
    try:
        import imageio_ffmpeg
        import yt_dlp
    except ImportError as exc:
        raise LinkAudioError('Link import needs yt-dlp and imageio-ffmpeg: '
                             'run .venv/bin/pip install -r requirements-dashboard.txt') from exc
    with tempfile.TemporaryDirectory() as folder:
        options = dict(
            format='bestaudio/best',
            outtmpl=str(Path(folder) / 'download.%(ext)s'),
            noplaylist=True,
            logger=_QuietLogger(),
            noprogress=True,
            max_filesize=MAX_DOWNLOAD_BYTES,
            match_filter=yt_dlp.utils.match_filter_func(f'duration <=? {MAX_SECONDS}'),
        )
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True) or {}
        except yt_dlp.utils.DownloadError as exc:
            reason = str(exc).removeprefix('ERROR: ').strip()
            raise LinkAudioError(f'Could not get audio from this link: {reason}') from exc
        source = next(Path(folder).glob('download.*'), None)
        if source is None:
            raise LinkAudioError(f'No audio was downloaded. Posts longer than {MAX_SECONDS // 60} minutes are skipped.')
        # The bundled ffmpeg has no ffprobe, so convert directly instead of using yt-dlp's post-processor.
        wav = Path(folder) / 'audio.wav'
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-loglevel', 'error', '-i', str(source),
                                 '-vn', '-ac', '2', '-c:a', 'pcm_s16le', str(wav)],
                                capture_output=True, text=True, timeout=300)
        if result.returncode or not wav.exists():
            raise LinkAudioError('This post has no audio track.')
        return wav.read_bytes(), (info.get('title') or 'Linked audio').strip()


class _QuietLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass
