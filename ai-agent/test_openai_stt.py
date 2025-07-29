from openai import OpenAI
import os

# Set your OpenAI API key here or via the OPENAI_API_KEY environment variable
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")  # <-- Put your key here if not using env var

AUDIO_PATH = "/root/livekit.ecommcube.com/ai-agent/test.wav"  # Your audio file
# MODEL_NAME = "gpt-4o-transcribe"  # or "whisper-1"
# MODEL_NAME = "whisper-1"
MODEL_NAME = "gpt-4o-mini-transcribe"

client = OpenAI(api_key=OPENAI_API_KEY)

try:
    with open(AUDIO_PATH, "rb") as f:
        transcript = client.audio.transcriptions.create(
            file=f,
            model=MODEL_NAME,
            response_format="text",  # or "json", "verbose_json"
        )
    print("\n--- TRANSCRIPT ---\n")
    print(transcript)
except FileNotFoundError:
    print(f"Audio file not found: {AUDIO_PATH}")
except Exception as e:
    print(f"Error during transcription: {e}")
