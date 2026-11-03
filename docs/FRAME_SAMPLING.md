# Verified frame sampling

`videorag.frames.sample_frames(record, source_path, output_dir, cadence_s=5)` takes a
registered `MediaRecord` and one of its verified source paths. It rehashes the source
before and after extraction, samples PNGs at 0, cadence, ... strictly before the
registered duration, and writes `output_dir/<video_id>/frames.json` last. By default
it refuses more than 1,000 frames. FFmpeg and FFprobe are required for registration;
FFmpeg is required for extraction. The output directory belongs under ignored `data/`
or `artifacts/`, outside git.

```python
from videorag import register_video
from videorag.frames import sample_frames, load_frame_manifest

record = register_video("data/video.mp4", "data/media_manifest.json").record
frames = sample_frames(record, "data/video.mp4", "data/frames", cadence_s=5)
assert load_frame_manifest("data/frames/" + record.asset.video_id + "/frames.json") == frames
```

Each `FrameArtifact` has a point timestamp, a content-derived `frame_ref`, a PNG
digest, and a filename. The manifest records the FFmpeg version line and stream
index. `load_frame_manifest` checks the PNG bytes by default.
An OCR or description extractor can later use `frame_ref` as its observation's
frame reference and provenance locator. Sampling alone produces no OCR text or
description and makes no claim about actions between sample times. An existing
different manifest or altered PNG is rejected; choose a new output directory
for a different cadence or extraction configuration. This is a single-writer
local artifact workflow; it does not update processing status automatically.
