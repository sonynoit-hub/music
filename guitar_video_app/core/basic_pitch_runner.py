"""Run Basic Pitch on one WAV and save MIDI plus onset peaks.

Standalone (only Basic Pitch imports) so it can run inside a separate Python environment:
python basic_pitch_runner.py WAV OUTPUT_DIR SETTINGS_JSON
"""
import json
from pathlib import Path
import sys

ONSET_PEAK_MIN = 0.3


def run(wav: str, output_dir: str, settings: dict) -> Path:
    from basic_pitch.inference import ICASSP_2022_MODEL_PATH, predict
    from basic_pitch.note_creation import MIDI_OFFSET, model_frames_to_time

    wav_path, out = Path(wav), Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    model_output, midi_data, _ = predict(str(wav_path), ICASSP_2022_MODEL_PATH, **settings)
    midi_path = out / f'{wav_path.stem}_basic_pitch.mid'
    midi_data.write(str(midi_path))

    onset = model_output['onset']
    times = model_frames_to_time(onset.shape[0])
    peaks = []
    for frame in range(1, onset.shape[0] - 1):
        for column in range(onset.shape[1]):
            value = float(onset[frame, column])
            if value >= ONSET_PEAK_MIN and value >= onset[frame - 1, column] and value > onset[frame + 1, column]:
                peaks.append([round(float(times[frame]), 4), column + MIDI_OFFSET, round(value, 3)])
    midi_path.with_suffix('.onsets.json').write_text(json.dumps(peaks), encoding='utf-8')
    return midi_path


if __name__ == '__main__':
    print(run(sys.argv[1], sys.argv[2], json.loads(sys.argv[3])))
