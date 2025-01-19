"""Support to search YouTube videos."""

import yt_dlp
import webvtt
import os
import tempfile


def get_youtube_doc(url):
    """Return a descriptive string and citation for thea YouTube video.

    Args:
       URL: string url to the video.

    Returns:
       doc, citation
    """
    fd, path = tempfile.mkstemp()

    ydl_opts = {
        "writeautomaticsub": True,
        "subtitlesformat": "srt",
        "skip_download": True,
        "outtmpl": path,
        "quiet": True,
    }

    vtt = ydl_opts["outtmpl"] + ".en.vtt"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

        info_dict = ydl.extract_info(url, download=False)
        title = info_dict.get("title")
        description = info_dict.get("description")

        if os.path.exists(vtt):
            transcript = " ".join([caption.text for caption in webvtt.read(vtt)])
        else:
            transcript = "No transcript found"

    os.remove(path)

    doc = f"Title: {title}\n\n"
    doc += f"Description: {description}\n\n"
    doc += f"Transcript: {transcript}"

    return doc, f"{title}. {url}."
