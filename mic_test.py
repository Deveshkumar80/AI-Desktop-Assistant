import sounddevice as sd
import numpy as np

print("Default audio devices:", sd.default.device)

# Get the default input device
mic_id = sd.default.device[0]

if mic_id is None or mic_id < 0:
    print("No default microphone selected.")
    print("Open Windows Settings > System > Sound > Input.")
    raise SystemExit

mic_info = sd.query_devices(mic_id)

print("Selected microphone:", mic_info)

# Use the microphone's reported default sample rate
sample_rate = int(mic_info["default_samplerate"])

print(f"\nRecording at {sample_rate} Hz for 5 seconds.")
print("Speak now...")

try:
    audio = sd.rec(
        int(5 * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=mic_id,
    )

    sd.wait()

    volume = float(np.max(np.abs(audio)))

    print("\nMicrophone volume:", volume)

    if volume < 0.005:
        print("Microphone opened, but little or no sound was detected.")
    else:
        print("Sound detected successfully!")

except Exception as error:
    print("\nMicrophone recording failed:")
    print(error)