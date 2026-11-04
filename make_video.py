#!/usr/bin/env python3
"""Create an evidence-backed caption-only Forkshift demo MP4.

All visuals are original Pillow drawings derived from the checked-in JSON
recordings. AVFoundation encodes the still frames. No browser, screen capture,
audio, network, or live inference is used.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "Forkshift-Demo.mp4"
W, H = 1280, 720
BG = (10, 16, 24)
PANEL = (18, 29, 42)
PANEL2 = (14, 24, 36)
EDGE = (35, 53, 74)
INK = (229, 239, 251)
MUTED = (154, 175, 199)
MINT = (101, 237, 211)
RED = (255, 140, 135)
AMBER = (255, 208, 134)
BLUE = (134, 185, 253)
GREEN_DARK = (20, 50, 51)
RED_DARK = (57, 34, 42)


def font(size: int, mono: bool = False):
    candidates = (["/System/Library/Fonts/Menlo.ttc"] if mono else []) + [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def rounded(d, box, fill=PANEL, outline=EDGE, radius=16, width=2):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrap(d, text, fnt, max_width):
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if d.textbbox((0, 0), candidate, font=fnt)[2] <= max_width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def paragraph(d, x, y, text, fnt, fill=MUTED, max_width=700, gap=8):
    for line in wrap(d, text, fnt, max_width):
        d.text((x, y), line, font=fnt, fill=fill)
        y += fnt.size + gap
    return y


def canvas(section, evidence):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.ellipse((980, -320, 1530, 230), fill=(18, 37, 56))
    d.ellipse((-280, 585, 190, 1035), fill=(15, 37, 43))
    rounded(d, (52, 35, 86, 69), MINT, MINT, 9, 1)
    d.text((61, 39), "↯", font=font(21), fill=(7, 38, 33))
    d.text((99, 39), "Forkshift", font=font(20), fill=INK)
    d.text((1000, 46), "INFERENCE INCIDENT LAB", font=font(12, True), fill=MUTED)
    d.line((52, 88, 1228, 88), fill=EDGE, width=2)
    d.line((52, 670, 1228, 670), fill=EDGE, width=1)
    d.text((52, 684), section.upper(), font=font(12, True), fill=MINT)
    d.text((500, 684), evidence, font=font(12, True), fill=MUTED)
    d.text((1123, 684), "SYNTHETIC", font=font(11, True), fill=AMBER)
    return im, d


def header(d, kicker, title, subtitle=None):
    d.text((58, 116), kicker.upper(), font=font(14, True), fill=MINT)
    d.text((58, 148), title, font=font(39), fill=INK)
    if subtitle:
        paragraph(d, 60, 204, subtitle, font(18), MUTED, 760, 7)


def metric(d, box, label, value, tint=MINT, detail=None):
    x, y, w, h = box
    rounded(d, (x, y, x + w, y + h), PANEL, EDGE, 14, 2)
    d.text((x + 17, y + 14), label.upper(), font=font(11, True), fill=MUTED)
    d.text((x + 17, y + 37), value, font=font(28), fill=tint)
    if detail:
        d.text((x + 17, y + h - 25), detail, font=font(12), fill=MUTED)


def pill(d, x, y, text, color=MINT, background=GREEN_DARK, width=0):
    f = font(12, True)
    w = width or d.textbbox((0, 0), text, font=f)[2] + 22
    rounded(d, (x, y, x + w, y + 29), background, background, 12, 1)
    d.text((x + 11, y + 7), text, font=f, fill=color)


def draw_queue_chart(d, unchanged, model, x=78, y=336, w=770, h=246):
    # Both lines are read directly from rank-drop reference replay timelines.
    rows_a, rows_b = unchanged["timeline"], model["timeline"]
    values = [r["voice_queue"] for r in rows_a + rows_b]
    vmax = max(1, max(values))
    left, right, top, bottom = x + 58, x + w - 22, y + 18, y + h - 36
    for n in range(5):
        yy = bottom - (bottom - top) * n / 4
        d.line((left, yy, right, yy), fill=EDGE, width=1)
        d.text((x + 6, yy - 8), str(round(vmax * n / 4)), font=font(10, True), fill=MUTED)
    fx = left + (right - left) * 12 / 59
    rx = left + (right - left) * 44 / 59
    d.rectangle((fx, top, rx, bottom), fill=(34, 34, 37))
    d.line((fx, top, fx, bottom), fill=AMBER, width=2)
    d.line((rx, top, rx, bottom), fill=(115, 96, 61), width=1)
    d.text((fx + 6, top + 4), "WORKER FAULT", font=font(10, True), fill=AMBER)
    d.text((left - 4, bottom + 10), "0s", font=font(10, True), fill=MUTED)
    d.text((fx - 11, bottom + 10), "12s", font=font(10, True), fill=MUTED)
    d.text((rx - 10, bottom + 10), "44s", font=font(10, True), fill=MUTED)
    d.text((right - 22, bottom + 10), "59s", font=font(10, True), fill=MUTED)

    def pts(rows):
        out = []
        for row in rows:
            xx = left + (right - left) * row["t"] / 59
            yy = bottom - (bottom - top) * row["voice_queue"] / vmax
            out.append((xx, yy))
        return out
    d.line(pts(rows_a), fill=RED, width=4, joint="curve")
    d.line(pts(rows_b), fill=MINT, width=4, joint="curve")
    d.ellipse((fx - 6, pts(rows_a)[12][1] - 6, fx + 6, pts(rows_a)[12][1] + 6), fill=RED)
    d.ellipse((fx - 6, pts(rows_b)[12][1] - 6, fx + 6, pts(rows_b)[12][1] + 6), fill=MINT)
    d.line((x + 5, y + h + 17, x + 35, y + h + 17), fill=RED, width=4)
    d.text((x + 43, y + h + 9), "UNCHANGED", font=font(10, True), fill=MUTED)
    d.line((x + 188, y + h + 17, x + 218, y + h + 17), fill=MINT, width=4)
    d.text((x + 226, y + h + 9), "LLAMA PLAN", font=font(10, True), fill=MUTED)


def scene_intro():
    im, d = canvas("01 · incident brief", "Source: evidence/rank-drop.json")
    header(d, "Test the recovery before you route traffic", "A worker drops mid-rush.",
           "Can an operator protect live voice, preserve batch work, and obey the alternate-pool policy?")
    rounded(d, (60, 330, 1220, 600), PANEL, EDGE, 20, 2)
    # Original diagram of the synthetic service topology.
    boxes = [(106, 404, 342, 522), (462, 404, 698, 522), (818, 404, 1054, 522)]
    labels = [("PRIMARY RANK", "18 → 3 capacity", BLUE), ("LIVE VOICE", "deadline ≥ 97%", MINT), ("ALT POOL", "voice only", AMBER)]
    for box, (title, sub, color) in zip(boxes, labels):
        rounded(d, box, PANEL2, EDGE, 16, 2)
        d.text((box[0] + 22, box[1] + 24), title, font=font(13, True), fill=color)
        d.text((box[0] + 22, box[1] + 57), sub, font=font(19), fill=INK)
    d.line((343, 463, 457, 463), fill=MINT, width=4)
    d.polygon([(457, 463), (442, 454), (442, 472)], fill=MINT)
    d.line((699, 463, 813, 463), fill=EDGE, width=3)
    d.polygon([(813, 463), (798, 454), (798, 472)], fill=EDGE)
    d.text((467, 537), "SIMULATED QUEUE REPLAY", font=font(11, True), fill=MUTED)
    d.text((60, 616), "Every percentage below comes from the saved simulator replays.", font=font(15), fill=MUTED)
    return im


def scene_queue(rank):
    unchanged = rank["branches"]["unchanged"]["replays"]["reference"]
    llama = rank["branches"]["llama"]["replays"]["reference"]
    im, d = canvas("02 · queue replay", "Source: rank-drop · reference trace")
    header(d, "Simulated 60-second trace", "The unchanged queue collapses.",
           "At simulated second 12, primary capacity falls from 18 to 3 requests per second.")
    rounded(d, (60, 305, 870, 614), PANEL, EDGE, 18, 2)
    draw_queue_chart(d, unchanged, llama)
    metric(d, (900, 325, 286, 120), "Voice on time · unchanged", f"{unchanged['voice']['rate']*100:.1f}%", RED,
           f"{unchanged['voice']['expired']} expired")
    d.text((928, 450), "↓", font=font(34), fill=MUTED)
    metric(d, (900, 494, 286, 120), "Voice on time · Llama", f"{llama['voice']['rate']*100:.0f}%", MINT,
           "all 3 traffic replays pass")
    return im


def scene_panic(rank):
    b = rank["branches"]["panic"]
    voice = b["replays"]["reference"]["voice"]["rate"] * 100
    alt_batch = b["replays"]["reference"]["alternate_batch"]
    im, d = canvas("03 · safety gate", "Source: rank-drop.json · panic branch")
    header(d, "A faster answer can still be unsafe", "Emergency reroute is rejected.",
           "The panic plan moves all traffic to the alternate pool. That pool is approved for voice only.")
    rounded(d, (60, 312, 760, 594), PANEL, EDGE, 18, 2)
    d.text((95, 341), "PANIC PLAN", font=font(13, True), fill=RED)
    rows = [("Overflow", b["plan"]["overflow"]), ("Batch admission", f"{b['plan']['batch_admit_pct']}%"),
            ("Primary voice reserve", f"{b['plan']['reserve_pct']}%")]
    for i, (label, value) in enumerate(rows):
        yy = 390 + i * 52
        d.text((98, yy), label, font=font(17), fill=MUTED)
        d.text((498, yy), value, font=font(17, True), fill=INK)
        d.line((96, yy + 32, 715, yy + 32), fill=EDGE, width=1)
    rounded(d, (800, 312, 1219, 594), RED_DARK, (102, 53, 58), 18, 2)
    pill(d, 834, 344, "BLOCKED BY POLICY", RED, RED_DARK, 184)
    d.text((836, 397), f"{voice:.0f}%", font=font(42), fill=MINT)
    d.text((837, 444), "voice on time", font=font(15), fill=MUTED)
    d.line((836, 484, 1183, 484), fill=(102, 53, 58), width=1)
    paragraph(d, 836, 505, "Batch is prohibited on the alternate pool.", font(18), RED, 345, 6)
    return im


def scene_canary(rank):
    attempts = rank["canary"]["attempts"]
    im, d = canvas("04 · local canary", "Source: rank-drop.json · recorded probe")
    header(d, "A real local request path", "Probe → fault → alternate → restore.",
           "Four saved loopback HTTP outcomes share one probe ID. Both model tags run on the same local Ollama instance.")
    xs = [65, 360, 655, 950]
    colors = [MINT, RED, AMBER, MINT]
    for i, (x, a, tint) in enumerate(zip(xs, attempts, colors)):
        rounded(d, (x, 337, x + 248, 548), PANEL, EDGE, 17, 2)
        d.text((x + 20, 359), ["HEALTHY", "INJECTED FAULT", "FAILOVER", "RESTORED"][i], font=font(11, True), fill=MUTED)
        d.text((x + 20, 392), str(a["status"]), font=font(42), fill=tint)
        d.text((x + 20, 452), a["pool"].upper(), font=font(12, True), fill=INK)
        d.text((x + 20, 477), a["model"], font=font(13, True), fill=BLUE)
        if a.get("latency_ms"):
            d.text((x + 20, 514), f"{a['latency_ms']} ms · response", font=font(11), fill=MUTED)
        if i < 3:
            d.line((x + 250, 438, x + 287, 438), fill=EDGE, width=3)
            d.polygon([(x + 287, 438), (x + 276, 432), (x + 276, 444)], fill=EDGE)
    rounded(d, (65, 568, 1198, 622), PANEL2, EDGE, 13, 1)
    d.text((88, 586), "forkshift-voice-01", font=font(14, True), fill=MINT)
    d.text((338, 586), "Llama 3.1 8B", font=font(14, True), fill=BLUE)
    d.text((555, 586), "and", font=font(14), fill=MUTED)
    d.text((598, 586), "Llama 3.2 3B", font=font(14, True), fill=BLUE)
    d.text((825, 586), "one Ollama instance", font=font(14), fill=INK)
    return im


def scene_slow_recovery(no_crossing):
    llama = no_crossing["branches"]["llama"]
    revision = no_crossing["branches"]["revision"]
    r = llama["replays"]["slow-recovery"]
    im, d = canvas("05 · restricted pool", "Source: no-crossing.json · recorded runs")
    header(d, "No cross-pool routing allowed", "The first Llama plan misses recovery.",
           "Targets: voice ≥ 96% · batch ≥ 36% · alternate traffic = 0.")
    metric(d, (62, 310, 350, 142), "Voice on time", f"{r['voice']['rate']*100:.0f}%", MINT,
           "target met")
    metric(d, (375, 310, 350, 142), "Batch · slow recovery", f"{r['batch']['rate']*100:.1f}%", RED,
           "below 36% floor")
    metric(d, (688, 310, 232, 142), "Alternate use", f"{r['alternate_rate']*100:.0f}%", MINT,
           "restricted traffic stays")
    rounded(d, (948, 310, 1218, 452), RED_DARK, (102, 53, 58), 15, 2)
    d.text((974, 335), "GATE", font=font(11, True), fill=RED)
    d.text((974, 368), "BLOCKED", font=font(22, True), fill=RED)
    d.text((62, 486), "Model plan", font=font(14, True), fill=MUTED)
    plan = llama["plan"]
    d.text((62, 518), f"overflow {plan['overflow']}  ·  batch admit {plan['batch_admit_pct']}%  ·  reserve {plan['reserve_pct']}%",
           font=font(15, True), fill=INK)
    d.text((62, 556), "One feedback revision also missed the same slow-recovery batch floor.", font=font(17), fill=RED)
    d.text((62, 592), "Reference and demand-spike passed; slow-recovery did not.", font=font(15), fill=MUTED)
    return im


def scene_search(no_crossing):
    model = no_crossing["branches"]["llama"]["replays"]["slow-recovery"]
    search = no_crossing["branches"]["search"]["replays"]["slow-recovery"]
    im, d = canvas("06 · independent comparison", "Source: no-crossing.json · slow recovery")
    header(d, "Search checks the full bounded plan space", "Exhaustive search clears this case.",
           "The simulator enumerates 75 supported plans. On this saved trace, search passes all 3 replays; Llama plus its revision does not.")
    # Paired horizontal bars use evidence percentages and the 36% policy floor.
    x0, x1 = 355, 1000
    floor = x0 + (x1 - x0) * .36
    d.line((floor, 314, floor, 573), fill=AMBER, width=3)
    d.text((floor - 48, 287), "36% FLOOR", font=font(11, True), fill=AMBER)
    labels = [("Llama proposal", model["batch"]["rate"], RED),
              ("Exhaustive search", search["batch"]["rate"], MINT)]
    for i, (label, rate, tint) in enumerate(labels):
        yy = 366 + i * 118
        d.text((70, yy), label, font=font(18), fill=INK)
        d.text((70, yy + 35), "Voice on time 100% · alternate 0%", font=font(12, True), fill=MUTED)
        end = x0 + (x1 - x0) * rate
        rounded(d, (x0, yy + 5, x1, yy + 46), PANEL2, EDGE, 12, 1)
        rounded(d, (x0, yy + 5, end, yy + 46), tint, tint, 12, 1)
        d.text((end + 15, yy + 9), f"{rate*100:.1f}%", font=font(22), fill=tint)
        d.text((1045, yy + 12), "FAIL" if rate < .36 else "PASS", font=font(16, True), fill=tint)
    d.text((355, 585), "This scenario only · deterministic synthetic replay", font=font(12, True), fill=MUTED)
    return im


def scene_close():
    im, d = canvas("07 · what this proves", "Evidence bundle · no deployment")
    header(d, "A bounded operations prototype", "Test first. Gate the canary.",
           "Forkshift combines model proposals, deterministic replays, policy checks, and a local request-path drill.")
    cards = [
        (60, "SIMULATED LOAD", "Queue and capacity are synthetic."),
        (452, "LOCAL CANARY", "HTTP and Ollama tags; no GPU failover."),
        (844, "PLAN COMPARISON", "Search beats this model plan on one case."),
    ]
    for x, title, body in cards:
        rounded(d, (x, 337, x + 350, 515), PANEL, EDGE, 16, 2)
        d.text((x + 22, 362), title, font=font(12, True), fill=MINT)
        paragraph(d, x + 22, 404, body, font(18), INK, 295, 8)
    rounded(d, (60, 546, 1192, 615), PANEL2, EDGE, 14, 1)
    d.text((84, 567), "Next evidence: a two-worker GPU fault drill, trace calibration, and an operator pilot.",
           font=font(17), fill=AMBER)
    return im


SWIFT_WRITER = r'''import AVFoundation
import AppKit
import CoreVideo
import CoreGraphics
import ImageIO
import Foundation

let args = CommandLine.arguments
guard args.count >= 4 else { fatalError("writer needs output, fps, frame paths") }
let output = URL(fileURLWithPath: args[1])
let fps = Int32(args[2])!
let paths = Array(args.dropFirst(3))
try? FileManager.default.removeItem(at: output)
let width = 1280, height = 720
let writer = try AVAssetWriter(outputURL: output, fileType: .mp4)
let settings: [String: Any] = [AVVideoCodecKey: AVVideoCodecType.h264,
  AVVideoWidthKey: width, AVVideoHeightKey: height,
  AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 2_800_000,
                                    AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel]]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input,
  sourcePixelBufferAttributes: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
                                kCVPixelBufferWidthKey as String: width,
                                kCVPixelBufferHeightKey as String: height,
                                kCVPixelBufferCGImageCompatibilityKey as String: true,
                                kCVPixelBufferCGBitmapContextCompatibilityKey as String: true])
writer.add(input)
writer.startWriting()
writer.startSession(atSourceTime: .zero)
for (index, path) in paths.enumerated() {
  while !input.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.01) }
  guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
        let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fatalError("cannot read \(path)") }
  var buffer: CVPixelBuffer?
  let status = CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, adaptor.pixelBufferPool!, &buffer)
  guard status == kCVReturnSuccess, let pb = buffer else { fatalError("pixel buffer allocation failed") }
  CVPixelBufferLockBaseAddress(pb, [])
  let context = CGContext(data: CVPixelBufferGetBaseAddress(pb), width: width, height: height,
    bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(pb), space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)!
  context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
  CVPixelBufferUnlockBaseAddress(pb, [])
  let pts = CMTime(value: Int64(index), timescale: fps)
  if !adaptor.append(pb, withPresentationTime: pts) { fatalError("append failed: \(writer.error?.localizedDescription ?? "unknown")") }
}
input.markAsFinished()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
if writer.status != .completed { fatalError("encode failed: \(writer.error?.localizedDescription ?? "unknown")") }
'''


def load_evidence():
    rank = json.loads((ROOT / "evidence" / "rank-drop.json").read_text())
    restricted = json.loads((ROOT / "evidence" / "no-crossing.json").read_text())
    # Guard every headline against accidental drift in the saved recordings.
    assert rank["branches"]["unchanged"]["replays"]["reference"]["voice"]["rate"] == 0.39633
    assert rank["branches"]["llama"]["replays"]["reference"]["voice"]["rate"] == 1.0
    assert rank["branches"]["panic"]["eligible"] is False
    assert rank["branches"]["panic"]["replays"]["reference"]["failures"] == ["Batch is prohibited on the alternate pool"]
    assert [a["status"] for a in rank["canary"]["attempts"]] == [200, 503, 200, 200]
    assert rank["canary"]["attempts"][2]["model"] == "llama3.2:3b"
    assert restricted["branches"]["llama"]["replays"]["slow-recovery"]["batch"]["rate"] == 0.288493
    assert restricted["branches"]["search"]["eligible"] is True
    assert restricted["branches"]["search"]["replays"]["slow-recovery"]["batch"]["rate"] == 0.377634
    return rank, restricted


def main():
    rank, restricted = load_evidence()
    frames = [
        scene_intro(),
        scene_queue(rank),
        scene_panic(rank),
        scene_canary(rank),
        scene_slow_recovery(restricted),
        scene_search(restricted),
        scene_close(),
    ]
    seconds_per_card = 13
    with tempfile.TemporaryDirectory(prefix="forkshift-video-") as td:
        folder = Path(td)
        paths = []
        for i, frame in enumerate(frames):
            png = folder / f"frame_{i:02d}.png"
            frame.save(png, optimize=True)
            paths.append(png)
        swift = folder / "write_movie.swift"
        swift.write_text(SWIFT_WRITER)
        movie_frames = [frame for frame in paths for _ in range(seconds_per_card)]
        subprocess.run(["swift", str(swift), str(OUT), "1", *map(str, movie_frames)],
                       check=True, cwd=ROOT)
    print(f"Wrote {OUT}")
    print(f"{len(frames)} original caption cards × {seconds_per_card} seconds = {len(frames)*seconds_per_card} seconds")
    print("No browser, screen capture, audio, network, or live inference used.")


if __name__ == "__main__":
    main()
