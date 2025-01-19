"""Library for audio sources."""

import requests
from transformers import pipeline
import os
import tempfile


def is_audio_url(url):
    """Check if a given URL points to an audio file.

    Args:
        url: The URL to check.

    Returns:
        True if the URL points to an audio file, False otherwise.
    """
    try:
        response = requests.head(url, allow_redirects=True)
        response.raise_for_status()  # Raise an exception for bad status codes

        content_type = response.headers.get("Content-Type")
        return content_type and content_type.startswith("audio/")

    except requests.exceptions.RequestException:
        return False


def get_audio_text(path):
    """Generate a transcript for the item at PATH.

    Args:
      path: The URL of the podcast episode or audio file.

    Returns:
      str: The generated transcript of the audio.

    """
    try:
        if os.path.exists(os.path.expanduser(path)):
            audio = os.path.expanduser(path)
        elif path.startswith("http") and is_audio_url(path):
            response = requests.get(path)
            response.raise_for_status()
            audio = response.content
        else:
            raise f"Nothing found for {path}"

        # Use a pre-trained model (e.g., Whisper) for transcription
        # Install with: `pip install transformers`
        transcriber = pipeline(
            "automatic-speech-recognition",
            model="openai/whisper-small",
            # On mac, mps doesn't support float64...
            device="cpu",
        )

        transcript = transcriber(audio, return_timestamps=True)["text"]

        return transcript

    except requests.exceptions.RequestException as e:
        print(f"Error fetching audio from URL: {e}")
        return None
    except Exception as e:
        print(f"Error during transcription: {e}")
        return None


def record():
    """Make a recording to a tempfile.

    Returns the audio filename it is recorded in.
    """
    import pyaudio
    import wave
    import threading

    # Parameters for recording
    FORMAT = pyaudio.paInt16
    CHANNELS = 2
    RATE = 44100
    CHUNK = 1024

    _, audio_file = tempfile.mkstemp(suffix=".wav")

    # Initialize PyAudio
    audio = pyaudio.PyAudio()

    # Function to record audio
    def record_audio():
        # Open stream
        stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
        print("    Recording... Press Enter to stop.")

        frames = []

        # Record until Enter is pressed
        while not stop_recording.is_set():
            data = stream.read(CHUNK)
            frames.append(data)

        # Stop and close the stream
        stream.stop_stream()
        stream.close()

        # Save the recorded data as a WAV file
        wf = wave.open(audio_file, "wb")
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
        wf.close()
        print("    Done recording. Transcribing...")

    # Event to signal when to stop recording
    stop_recording = threading.Event()

    # Start recording in a separate thread
    recording_thread = threading.Thread(target=record_audio)
    recording_thread.start()

    # Wait for Enter key press to stop recording
    input()
    stop_recording.set()

    # Wait for the recording thread to finish
    recording_thread.join()

    # Terminate PyAudio
    audio.terminate()

    return audio_file
