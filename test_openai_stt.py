import requests

# Replace with your OpenAI API key
OPENAI_API_KEY = "sk-..."  # <-- Put your key here

# Path to your audio file
AUDIO_FILE_PATH = "test.wav"  # Change to your file

# OpenAI Whisper endpoint
url = "https://api.openai.com/v1/audio/transcriptions"

headers = {
    "Authorization": f"Bearer {OPENAI_API_KEY}"
}

files = {
    "file": (AUDIO_FILE_PATH, open(AUDIO_FILE_PATH, "rb"), "audio/wav"),
    "model": (None, "whisper-1"),
    # Optionally, you can add "language": (None, "en") for English
}

response = requests.post(url, headers=headers, files=files)

if response.status_code == 200:
    print("Transcription result:")
    print(response.json()["text"])
else:
    print("Error:", response.status_code)
    print(response.text) 