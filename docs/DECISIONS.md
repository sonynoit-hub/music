# Architectural Decisions

This file records project decisions and rationale so future work does not need the original conversation history.

## 1. Reuse The Existing Guitar Project

Decision: Continue from `/Users/dc/CodexProjects/guitar` rather than starting a new project.

Rationale: This project already contains useful Blender scenes, MIDI/WAV outputs, V2 lesson tests, dashboard code, and Blender bridge code.

## 2. Use `outputs/v3-tests.blend` As Latest Scene Candidate

Decision: Treat `outputs/v3-tests.blend` as the latest known Blender scene candidate unless the user selects another file.

Rationale: It is newer than `outputs/lesson-v2-tests.blend` and `outputs/reference-guitar.blend`, and appears to match the user's memory of the latest scene.

Superseded by decision 22: renders use `outputs/v4-vertical.blend`, built from this scene.

## 3. Use MIDI As The Structured Music Source

Decision: V1 uses MIDI for musical structure.

Rationale: MIDI already contains notes, ticks, PPQ, tempo changes, time signatures, and tracks. This avoids unreliable audio transcription in the first version.

## 4. Use Final WAV As Master Audio

Decision: V1 uses the final WAV for rendered audio.

Rationale: MIDI provides structure, but the WAV is the sound the viewer should hear. Blender syncs visuals to the WAV using seconds-based timing and `audio_offset`.

## 5. Keep Musical Analysis Outside Blender

Decision: Python owns MIDI parsing, musical timing, measure calculation, and guitar mapping. Blender only renders.

Rationale: Blender is better as a visual renderer than as a music-analysis engine. Keeping analysis outside Blender makes the JSON contract testable and keeps renders deterministic.

## 6. Preserve Ticks And Seconds

Decision: Export both tick-based timing and seconds-based timing.

Rationale: Ticks preserve musical structure. Seconds are required for audio and Blender timeline sync.

## 7. Make JSON The Python-To-Blender Contract

Decision: Normalized JSON is the boundary between analysis and rendering.

Rationale: A stable contract lets the analyzer and Blender importer evolve independently while making import bugs easier to isolate.

## 8. Rebuild Song-Specific Data On Import

Decision: Importing a new song rebuilds song-specific measures, notes, tabs, animations, and audio.

Rationale: Song data should never leak from one import to the next. Reusable scene setup should remain intact.

## 9. Freeze V1 Before Advanced Features

Decision: V1 excludes WAV-to-MIDI, velocity interpretation, chord/key/section detection, AI transcription, and advanced guitar techniques.

Rationale: The first milestone is reliable synchronization and rendering. Higher-level musical interpretation can be added after the base pipeline works.

## 10. Add Normalized Export Beside Existing V2

Decision: Add `guitar_video_app/core/normalized_song.py`, `guitar_video_app/core/music_analyzer.py`, and the `normalize-midi` CLI command without replacing the existing V2 lesson renderer.

Rationale: The current V2 dashboard and Blender workflow is already verified. A separate normalized exporter lets the project prove the MIDI-to-JSON contract first, then add compatibility conversion or direct Blender import with lower risk.

## 11. Convert Normalized JSON To V2 Before Direct Blender Import

Decision: Add a normalized-to-V2 compatibility bridge for fixed-tempo, single-time-signature songs before changing Blender import behavior.

Rationale: V2 can already render beat-based lessons reliably, but it cannot represent tempo maps or time-signature changes. The bridge lets MIDI-derived normalized songs use the existing renderer while keeping richer normalized JSON as the long-term contract.

## 12. Dashboard Stores Converted V2 For Normalized Imports

Decision: When the dashboard receives normalized JSON, it converts the file to V2 lesson JSON and stores that converted V2 file for preview and Blender transfer.

Rationale: This keeps the verified dashboard and Blender bridge unchanged while allowing the user to import normalized MIDI-derived song data. Direct normalized Blender import remains the later architecture step.

## 13. Render Videos In Background Blender From The Dashboard

Decision: The dashboard Render button runs `scripts/render_lesson.py` in a separate background Blender process (`Blender -b outputs/v3-tests.blend`) using the Workbench engine, 30 fps, and a 1080x1350 frame (now `outputs/v4-vertical.blend` at 1080x1920, see decision 22). Videos are stored in `data/dashboard/<song>/renders/`, named after the song (`<Song name>.mp4`, test renders `<Song name> (test).mp4`, with characters not allowed in file names replaced and a number added instead of replacing an earlier render). Only one render runs at a time.

Rationale: Rendering an animation from the Blender window crashes, because the lesson frame handler creates objects during the render. A background process avoids this, does not need the Blender window open, and leaves the open scene untouched. Lesson timing stays beat-based, so changing the render fps does not change musical timing.

## 14. Standard Notation Is A Dashboard Display Layer

Decision: The dashboard draws standard notation above the tab preview with VexFlow (vendored in `guitar_video_app/ui/vexflow.min.js`). Notes are snapped to a 16th-note grid for display only, written an octave above sounding pitch, and split into a melody voice (strings 1-3, stems up) and a bass voice (strings 4-6, stems down). No key signature is shown; accidentals use sharps.

Rationale: The lesson JSON and Blender timing stay unquantized and authoritative, so the notation cannot change sync. Key detection is outside V1, so notation uses C with accidentals until a key is part of the song data.

## 15. Re-Time Lessons Without Moving Notes In Time

Decision: The dashboard can re-grid a lesson with a tempo and a first-beat time (`guitar_video_app/core/retime.py`, `POST /api/songs/{id}/timing`). Every note keeps its audio time: beats are recomputed from seconds and the audio offset shifts by the same amount. Notes before the first beat get whole lead-in measures, except notes at most 30 ms early, which move onto the first beat. A suggestion endpoint fits note onsets to a 16th-note grid between 60 and 180 BPM.

Rationale: Audio transcription writes a placeholder 120 BPM, so measures and notation do not match the music even though note times in seconds are correct. Re-timing fixes measures, pages and notation without changing sync. The source MIDI file is left unchanged.

## 16. Import Audio From Links As A WAV Master

Decision: The dashboard can import a song's audio from a YouTube, Instagram or TikTok link (`guitar_video_app/integrations/link_audio.py`, `POST /api/songs/{id}/assets/link`). yt-dlp downloads the audio and a bundled ffmpeg (imageio-ffmpeg) converts it to 16-bit stereo WAV, which is stored exactly like an uploaded WAV. Only those three sites are accepted, playlists are ignored, and posts longer than 20 minutes are skipped.

Rationale: The pipeline keeps a final WAV as the audio authority, so every source ends as a WAV. A host allowlist keeps the downloader from fetching arbitrary URLs.

## 17. Optional Tidy Step For Transcribed Timing

Decision: A dashboard "Tidy notes" action (`tidy_lesson` in `guitar_video_app/core/retime.py`, `POST /api/songs/{id}/tidy`) cleans transcribed lessons on the 16th-note grid of the current tempo: note starts within 45 ms of a 16th move onto it, the same pitch repeated within 80 ms is merged, and each note holds until the next note in its voice (strings 1-3 or 4-6), up to 2 beats. It is opt-in and should run after the tempo is set.

Rationale: Transcription spreads chord notes over a few milliseconds and gives uneven lengths, which makes the tab and notation hard to read. Unlike re-timing, this does move notes in time, so the shift is capped at 45 ms and it runs only when the user asks.

## 18. Song-Level Fingering For MIDI Without String Tracks

Decision: The Guitar Mapper chooses string and fret for the whole song at once (`plan_positions` in `guitar_video_app/core/fingering_solver.py`). Notes starting within 40 ms are fingered as one chord, fretted notes in a chord span at most 4 frets, and a beam search keeps the hand in a 4-fret position when possible, prefers frets up to 7, and avoids reusing a string whose previous note is still ringing. Notes from tracks named "string N" keep that string.

Rationale: Transcribed MIDI almost never starts chord notes on the same tick, so choosing positions per exact-tick group with only the previous group in view jumped around the neck and put open-position music on frets 12-15. The mapper still runs in Python, so Blender only receives the chosen positions.

## 19. Cleaner Transcription And Automatic Timing On Generate MIDI

Decision: Generate MIDI runs Basic Pitch with onset threshold 0.6, frame threshold 0.4 and no melodia note extension (`SETTINGS` in `guitar_video_app/core/audio_transcription.py`). The raw MIDI is then cleaned (`guitar_video_app/core/transcription_cleanup.py`): a note at fret 8+ on the high E that starts with a louder note exactly 1-2 octaves or an octave and a fifth below is dropped as an overtone, and a note that starts where the same pitch just ended while more than 10% quieter is joined onto it as one held note. A quieter note under 0.16 s exactly 1-2 octaves or an octave and a fifth above a note starting within 80 ms is also dropped, as is a short quieter note running straight into a louder note of the same pitch. When a pitch has sounded three times at a steady spacing and Basic Pitch saw an onset (strength 0.4+, saved by `basic_pitch_runner.py` as `.onsets.json`) exactly where the next or previous repeat belongs, that note is restored. After fingering, the dashboard fits tempo and downbeat, re-times and tidies the lesson automatically. Tidy now picks an 8th grid unless over a tenth of notes sit on in-between 16ths, and snaps a note up to 80 ms behind a chord onto that chord, and splits voices into bass (strings 5-6, or a string-4 note held a beat or starting a measure, with no lower note from that measure still sounding) and melody instead of strings 1-3 and 4-6; bass notes may hold a full measure. The notation uses the same bass rule and grid. Imported MIDI files are not cleaned.

Rationale: Measured against a published tab of a fingerstyle recording (`data/benchmarks/passacaglia_reference.json`), the old defaults found 92% of real notes but 44% of detected notes were false (ringing notes detected again, overtones), which pushed fingering up to fret 19. The new chain keeps 93% of real notes with 6% false notes, 91% of matched notes on the same string and fret as the tab, and no fret above 5; repeated-note patterns (bass, moving line, repeated top note) come out the same in every measure. Re-timing keeps every note's audio time; tidy moves starts by at most 45 ms.

## 20. Optional Tempo Changes In Lesson V2

Decision: Lesson V2 JSON may carry `tempo_changes` (`[{"beat": "24", "bpm": 111}]`) after the starting `tempo_bpm`. All beat-to-seconds conversion goes through one tempo map in `guitar_video_app/core/lesson_v2.py` (`tempo_map`, `seconds_at`, `beat_at`), used by Blender playback, MIDI export, the dashboard summary and re-timing; the dashboard preview mirrors it in JavaScript. MIDI imports with real tempo changes now convert to V2 instead of being rejected. Automatic timing on Generate MIDI fits a tempo per measure after the global fit (`fit_tempo_map` in `guitar_video_app/core/retime.py`): a beam search over whole-BPM tempos within 80-125% of the global tempo, where a note costs 1 when it is more than 45 ms off its measure's grid and a tempo change costs 2, so a change only appears when it puts at least two more notes on the grid. Beat 0 and every note's audio time stay put. Afterwards, a pitch that starts on two grid lines up to 2 beats apart gets its next (or previous) repeat restored when Basic Pitch saw an onset of that pitch there (strength 0.4+), unless a note starting there explains it as an overtone (`restore_repeats`). The last bass note rings to its bar line once it lasts half the rest of the measure. Manual "Apply timing" still sets one tempo and drops tempo changes.

Rationale: Players slow down at phrase ends. With one tempo, the benchmark's closing measure drifted up to an 8th late, so every note there was drawn on the wrong beat and tidy could not snap it. With the fitted map (one change, 117.5 to 111 BPM) all 71 reference notes land on their exact beat, up from 59, with one extra note; on a steady 32-measure lesson with ±25 ms random timing the fit adds no tempo change. Keeping the map in Python keeps musical timing out of Blender, which only asks the shared module for seconds and beats.

## 21. Song Title Above The Guitar

Decision: Each dashboard song has a video title and an artist/songwriter line (`title` and `subtitle` columns; a NULL title means "use the song name", an empty one hides it), edited in the Render video panel. Send to Blender and renders pass them to `install_title` (`guitar_video_app/integrations/title_overlay.py`, `scripts/render_lesson.py --title --subtitle`), which places two centered camera-facing text objects (`Lesson_Title` in Georgia, `Lesson_Subtitle` in Georgia Italic, falling back to Blender's font) above the headstock and shrinks a line that would be wider than 88% of the frame. Send to Blender reloads the lesson modules so an open Blender picks up dashboard code changes.

Rationale: The title is video presentation, not lesson data, so it lives with the song rather than in lesson JSON, which Generate MIDI and imports replace.

## 22. Vertical 9:16 Video Replaces 4:5

Decision: Lessons render at 1080x1920 from `outputs/v4-vertical.blend`, which `scripts/make_vertical_scene.py` builds from the 4:5 scene `outputs/v3-tests.blend`: the orthographic camera frames 0.90 world units of height (about 15% closer than the 4:5 guitar) and shifts to keep the headstock in view and the neck above the tab. The white tab panel is a centered card from 11.5% to 88.5% of the width and 21% to 36% of the height, under the neck and in front of the guitar body, and the staff lines are centered from 14% to 86% of the width. Short-video apps draw captions over roughly the bottom 20% and buttons over the right 14%, so the panel sits above the captions and the buttons only cover the card's blank right margin; a full-width panel was also tried, but its white band dominated the frame and hid more of the guitar; an earlier version sat on the bottom edge and was hidden by captions. The resize goes through a camera-aligned parent empty (`App_Tab_Frame_9x16`) above the tab group, so the tilted tab scales along screen axes without shearing. The tab still shows two measures per page. Timing, tab layout code and the title overlay are unchanged; they read positions from the camera view.

Rationale: Short-form platforms show 9:16. Chosen from rendered mockups (`outputs/references_9x16/`, tab placement in `outputs/references_9x16_raised/` and `outputs/references_9x16_layout/`, chosen layout "P"): keeping the 4:5 guitar size left a large empty band and a thin tab, while this framing fills the frame and makes tab numbers larger on a phone. Building the scene with a script keeps the 4:5 scene reusable and the framing repeatable.
