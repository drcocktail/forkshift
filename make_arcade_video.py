#!/usr/bin/env python3
"""Render the caption-only Rescue Arcade cut from checked-in local evidence.

Original Pillow artwork is encoded by AVFoundation. This script only reads
three JSON recordings and never launches inference or makes a network request.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "arcade_evidence" / "final"
OUT = ROOT / "Forkshift-Rescue-Arcade.mp4"
REDSHIFT_REPORT = ROOT / "redshift_evidence" / "live-branch-trial.json"
if not REDSHIFT_REPORT.is_file():
    REDSHIFT_REPORT = REDSHIFT_REPORT.with_name("branch-trial.json")
TOTAL_CARDS = 10
SCENE_OFFSET = 0
W, H = 1280, 720
BG = (26, 22, 38)
PANEL = (47, 39, 59)
PANEL2 = (36, 31, 48)
EDGE = (84, 70, 97)
INK = (255, 248, 232)
MUTED = (196, 185, 202)
PINK = (255, 123, 145)
MINT = (140, 240, 198)
YELLOW = (255, 216, 121)
BLUE = (158, 183, 255)
RED = (255, 113, 135)
PURPLE = (203, 172, 236)


def font(size: int, mono: bool = False):
    options = (["/System/Library/Fonts/Menlo.ttc"] if mono else []) + [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
    ]
    for path in options:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def rounded(d, box, fill=PANEL, outline=EDGE, radius=20, width=2):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrap(d, text, f, width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if d.textbbox((0, 0), trial, font=f)[2] <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def paragraph(d, xy, text, f, fill=MUTED, width=800, gap=7):
    x, y = xy
    for line in wrap(d, text, f, width):
        d.text((x, y), line, font=f, fill=fill)
        y += f.size + gap
    return y


def critter(d, x, y, s, name, color, role, mood="smile", bob=0):
    """Original chunky little pixel-critters drawn from simple shapes."""
    y += bob
    outline = (48, 38, 57)
    # Ground shadow and tiny feet
    d.ellipse((x + 16*s, y + 118*s, x + 124*s, y + 132*s), fill=(21, 17, 31))
    # ears / antennae
    d.polygon([(x+20*s,y+40*s),(x+8*s,y+5*s),(x+43*s,y+28*s)], fill=color, outline=outline)
    d.polygon([(x+97*s,y+28*s),(x+132*s,y+2*s),(x+126*s,y+50*s)], fill=color, outline=outline)
    d.ellipse((x+41*s,y+4*s,x+59*s,y+22*s), fill=YELLOW, outline=outline, width=max(1,int(2*s)))
    d.ellipse((x+69*s,y+4*s,x+87*s,y+22*s), fill=YELLOW, outline=outline, width=max(1,int(2*s)))
    # Body, ears inset, tiny arms
    d.rounded_rectangle((x+16*s,y+25*s,x+125*s,y+119*s), radius=int(29*s), fill=color, outline=outline, width=max(2,int(4*s)))
    d.polygon([(x+25*s,y+39*s),(x+19*s,y+17*s),(x+43*s,y+34*s)], fill=tuple(min(255,c+24) for c in color), outline=outline)
    d.polygon([(x+98*s,y+34*s),(x+120*s,y+15*s),(x+115*s,y+45*s)], fill=tuple(min(255,c+24) for c in color), outline=outline)
    # face
    if mood == "sleep":
        d.arc((x+42*s,y+61*s,x+61*s,y+77*s), 195, 340, fill=outline, width=max(2,int(3*s)))
        d.arc((x+80*s,y+61*s,x+99*s,y+77*s), 195, 340, fill=outline, width=max(2,int(3*s)))
    elif mood == "ouch":
        d.line((x+43*s,y+66*s,x+59*s,y+75*s), fill=outline, width=max(2,int(4*s)))
        d.line((x+59*s,y+66*s,x+43*s,y+75*s), fill=outline, width=max(2,int(4*s)))
        d.line((x+82*s,y+66*s,x+98*s,y+75*s), fill=outline, width=max(2,int(4*s)))
        d.line((x+98*s,y+66*s,x+82*s,y+75*s), fill=outline, width=max(2,int(4*s)))
    else:
        d.ellipse((x+43*s,y+62*s,x+52*s,y+75*s), fill=outline)
        d.ellipse((x+88*s,y+62*s,x+97*s,y+75*s), fill=outline)
    d.arc((x+59*s,y+74*s,x+83*s,y+96*s), 15, 160, fill=(151,57,93) if mood!="ouch" else outline, width=max(2,int(3*s)))
    d.ellipse((x+29*s,y+79*s,x+42*s,y+87*s), fill=(255,160,180))
    d.ellipse((x+100*s,y+79*s,x+113*s,y+87*s), fill=(255,160,180))
    d.line((x+34*s,y+111*s,x+22*s,y+123*s), fill=outline, width=max(3,int(5*s)))
    d.line((x+107*s,y+111*s,x+120*s,y+123*s), fill=outline, width=max(3,int(5*s)))
    d.text((x+6*s,y+137*s), name, font=font(int(16*s)), fill=INK)
    d.text((x+6*s,y+159*s), role.upper(), font=font(max(9,int(9*s)), True), fill=MUTED)


def base(section, source, index, total):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.ellipse((970, -280, 1510, 260), fill=(48, 38, 63))
    d.ellipse((-240, 570, 220, 1010), fill=(31, 55, 54))
    rounded(d, (48, 31, 87, 70), YELLOW, YELLOW, 12, 1)
    d.text((57, 32), "↗", font=font(26), fill=(49, 33, 56))
    d.text((101, 33), "Forkshift", font=font(19), fill=INK)
    d.text((220, 40), "• RESCUE ARCADE", font=font(13, True), fill=PINK)
    d.text((938, 42), "LOCAL EVIDENCE CUT", font=font(11, True), fill=MUTED)
    d.line((49, 87, 1230, 87), fill=EDGE, width=2)
    d.line((49, 668, 1230, 668), fill=EDGE, width=1)
    d.text((51, 684), section.upper(), font=font(11, True), fill=MINT)
    d.text((510, 684), source, font=font(10, True), fill=MUTED)
    d.text((1155, 684), f"{index+SCENE_OFFSET:02d}/{total:02d}", font=font(11, True), fill=YELLOW)
    return im, d


def title(d, kicker, heading, subtitle, color=MINT):
    d.text((60, 111), kicker.upper(), font=font(12, True), fill=color)
    d.text((58, 142), heading, font=font(38), fill=INK)
    paragraph(d, (61, 196), subtitle, font(17), MUTED, 910, 7)


def badge(d, x, y, w, label, value, detail, good=True):
    tint = MINT if good else RED
    rounded(d, (x, y, x+w, y+126), (34,47,54) if good else (61,37,50), tint, 19, 2)
    d.text((x+17,y+14), label.upper(), font=font(11,True), fill=MUTED)
    d.text((x+17,y+39), value, font=font(26), fill=tint)
    paragraph(d,(x+17,y+82),detail,font(12),INK,w-32,3)


def ribbon(d, x, y, text, color=MINT, bg=(34,53,53), width=240):
    rounded(d,(x,y,x+width,y+32),bg,bg,14,1)
    d.text((x+12,y+8),text,font=font(11,True),fill=color)


def packet(d, x, y, s=1, color=YELLOW):
    d.rounded_rectangle((x,y,x+28*s,y+23*s),radius=5,fill=color,outline=(52,40,59),width=max(1,int(2*s)))
    d.line((x+6*s,y+7*s,x+21*s,y+7*s),fill=(52,40,59),width=max(1,int(2*s)))
    d.line((x+6*s,y+13*s,x+17*s,y+13*s),fill=(52,40,59),width=max(1,int(2*s)))


def find_event(record, event_type, pool=None, phase=None, occurrence=0):
    matches = [e for e in record["events"] if e["type"] == event_type
               and (pool is None or e.get("data", {}).get("pool") == pool)
               and (phase is None or e.get("data", {}).get("phase") == phase)]
    if len(matches) <= occurrence:
        raise AssertionError(f"missing event {event_type=} {pool=} {phase=} {occurrence=}")
    return matches[occurrence]


def event_scene(records, i, stage, title_text, caption, event_specs, scene_no, color=MINT):
    r = records["live-green-trap"]
    selected = [find_event(r, *spec) for spec in event_specs]
    im,d=base(f"LIVE RUN · {stage}","final/live-green-trap.json · local Ollama",scene_no,TOTAL_CARDS)
    title(d,"REAL LOCAL MODEL · LLAMA 3.2 3B",title_text,caption,color)
    rounded(d,(60,279,1220,600),PANEL,EDGE,22,2)
    # little event timeline
    d.text((87,302),"SAVED DECISION TRAIL",font=font(11,True),fill=MUTED)
    tx0,tx1=110,1163
    d.line((tx0,353,tx1,353),fill=EDGE,width=6)
    for j,e in enumerate(selected):
        x=tx0+(tx1-tx0)*j/max(1,len(selected)-1)
        tint=RED if e["type"] in ("fault","rollback") else YELLOW if e["type"] in ("decision","observation") else MINT
        d.ellipse((x-11,342,x+11,364),fill=tint,outline=(29,24,38),width=3)
        if j<len(selected):
            d.text((max(80,x-42),377),f"{e['seq']:02d} · {e['type'].upper()}",font=font(9,True),fill=tint)
    critter(d,165,414,1.05,"Pip",PURPLE,"primary worker", "ouch" if stage in ("FAULT","ROLLBACK") else "smile")
    critter(d,943,414,1.05,"Boba",MINT,"backup worker", "ouch" if stage=="FAULT" else "smile")
    # center connector and packet status
    y=479
    d.line((350,y,929,y),fill=color,width=5)
    d.polygon([(929,y),(911,y-9),(911,y+9)],fill=color)
    packet(d,617,y-11,1.0,YELLOW if stage in ("CANARY","FAULT") else MINT)
    ribbon(d,495,518,stage,color,(34,47,54) if color==MINT else (61,37,50),290)
    # selected events, readable evidence text
    words=[e["message"] for e in selected[:3]]
    paragraph(d,(87,562),"  •  ".join(words),font(12),MUTED,1085,3)
    return im


def scene_intro(records):
    im,d=base("MISSION BRIEF","three checked-in JSON records",1,TOTAL_CARDS)
    title(d,"FORKSHIFT · RESCUE ARCADE","A green light can go stale.","Two little local workers. One careful canary. One backup that exits right after the green check.",YELLOW)
    rounded(d,(60,285,1220,612),PANEL,EDGE,24,2)
    critter(d,170,365,1.35,"Pip",PURPLE,"PRIMARY · LLAMA 3.2 3B","sleep")
    critter(d,925,365,1.35,"Boba",MINT,"BACKUP · LLAMA 3.2 3B","smile")
    d.line((400,473,885,473),fill=EDGE,width=7)
    for x in (486,627,768): packet(d,x,461,.9,YELLOW)
    ribbon(d,514,414,"CANARY → COMMIT → VERIFY",MINT,(34,53,53),310)
    paragraph(d,(93,568),"Actual recorded event ledgers · synthetic scenario · no live inference in this export.",font(15),MUTED,1020)
    return im


def scene_after(records):
    r=records["live-green-trap"]
    im,d=base("GREEN CANARY · THEN STALE","final/live-green-trap.json · local Ollama",2,TOTAL_CARDS)
    title(d,"EVENTS 07–10","Green. Commit. Then—gone.","The backup passes its canary, the route commits, and the worker exits immediately afterward.",MINT)
    rounded(d,(60,282,1220,611),PANEL,EDGE,22,2)
    critter(d,142,379,1.0,"Pip",PURPLE,"primary · stopped","ouch")
    critter(d,994,379,1.0,"Boba",MINT,"backup · exited","ouch")
    d.line((312,466,965,466),fill=RED,width=5)
    packet(d,632,452,1.2,YELLOW)
    events=[find_event(r,"probe",pool="backup",phase="canary"),
            find_event(r,"commit",pool="backup"),
            find_event(r,"fault",pool="backup"),
            find_event(r,"probe",pool="backup",phase="golden")]
    for x,e in zip((104,383,690,964),events):
        col=MINT if e["type"] in ("probe","commit") and e["data"].get("status",200)!=0 else RED
        rounded(d,(x,301,x+212,359),(35,50,51) if col==MINT else (63,38,52),col,13,2)
        d.text((x+12,311),f"EVENT {e['seq']:02d} · {e['type'].upper()}",font=font(10,True),fill=col)
        paragraph(d,(x+12,334),e["message"],font(11),INK,190,3)
    ribbon(d,467,521,"CANARY GREEN ≠ FOREVER HEALTHY",YELLOW,(59,48,48),365)
    d.text((87,572),"The next real request catches the stale success: the backup is no longer there.",font=font(14),fill=MUTED)
    return im


def scene_rollback(records):
    r=records["live-green-trap"]
    im,d=base("POST-SWITCH CHECK · ROLLBACK","final/live-green-trap.json · local Ollama",3,TOTAL_CARDS)
    title(d,"EVENTS 11–19","The failed request triggers a rollback.","One golden request gets no response from the dead backup. The runtime guard rolls back; Llama then chooses to repair primary and proves it before committing.",RED)
    rounded(d,(60,280,1220,613),PANEL,EDGE,22,2)
    ev_dispatch=find_event(r,"dispatch",pool="backup",phase="golden")
    ev_failed=find_event(r,"probe",pool="backup",phase="golden")
    ev_rollback=find_event(r,"rollback",pool="primary")
    ev_repair=find_event(r,"decision",occurrence=1)
    ev_canary=find_event(r,"probe",pool="primary",phase="canary")
    ev_commit=find_event(r,"commit",pool="primary")
    steps=[(f"{ev_dispatch['seq']:02d} · GOLDEN",ev_dispatch["message"],YELLOW),
           (f"{ev_failed['seq']:02d} · NO RESPONSE",ev_failed["message"],RED),
           (f"{ev_rollback['seq']:02d} · ROLLBACK",ev_rollback["message"],MINT),
           (f"{ev_repair['seq']:02d} · LLAMA REPAIR",ev_repair["message"],BLUE),
           (f"{ev_canary['seq']:02d} · CANARY",ev_canary["message"],MINT),
           (f"{ev_commit['seq']:02d} · COMMIT",ev_commit["message"],MINT)]
    x0=91; gap=185
    for i,(head,body,col) in enumerate(steps):
        x=x0+i*gap
        rounded(d,(x,329,x+165,493),PANEL2,col,15,2)
        d.text((x+12,344),head,font=font(10,True),fill=col)
        paragraph(d,(x+12,374),body,font(13),INK,140,5)
        if i<5:
            d.line((x+166,410,x+183,410),fill=EDGE,width=3)
            d.polygon([(x+183,410),(x+176,405),(x+176,415)],fill=EDGE)
    critter(d,108,510,.62,"Pip",PURPLE,"back online")
    packet(d,606,556,1.25,MINT)
    d.text((657,551),"Repair commit only follows a passing canary.",font=font(14),fill=MUTED)
    return im


def scene_live_result(records):
    r=records["live-green-trap"]
    im,d=base("LIVE MODEL RESULT","final/live-green-trap.json · 2026-11-04",4,TOTAL_CARDS)
    title(d,"REAL OLLAMA INFERENCE · LLAMA 3.2 3B","Recovered—and policy-safe.","The oracle grades the complete routing ledger, not just the last successful request.",MINT)
    badge(d,72,300,516,"TASK RECOVERY","SERVICE RECOVERED","Both golden requests succeeded through repaired primary.",True)
    badge(d,692,300,516,"TRAFFIC SAFETY","SAFETY PASSED","Canary-attested commits; one rollback after the backup died.",True)
    rounded(d,(72,464,1208,602),PANEL,EDGE,18,2)
    for x,lab,val in [(98,"CORRECTION","1"),(378,"SUCCESSFUL PROBES","4"),(658,"FAILED PROBES","1"),(938,"ROLLBACKS","1")]:
        d.text((x,484),lab,font=font(11,True),fill=MUTED); d.text((x,517),val,font=font(27),fill=INK)
    d.text((99,568),f"Saved verdict: {r['verdict'].upper()} · engine: {r['engine']} · agent: {r['agent']}",font=font(13,True),fill=MINT)
    return im


def scene_sealed(records):
    r=records["live-sealed"]
    im,d=base("SEALED ROUTE · LOCAL REPAIR","final/live-sealed.json · local Ollama",5,TOTAL_CARDS)
    title(d,"A DIFFERENT REAL LLAMA RUN","Backup blocked before dispatch.","This route is outside the owner policy. The worker asks to inspect it; the gate refuses before traffic is sent.",BLUE)
    rounded(d,(62,291,1218,599),PANEL,EDGE,20,2)
    # roadblock and no packet crossing
    critter(d,137,372,1.0,"Pip",PURPLE,"primary · stopped","ouch")
    critter(d,988,372,1.0,"Boba",MINT,"backup · restricted")
    d.line((334,458,948,458),fill=EDGE,width=5)
    d.line((626,432,626,485),fill=RED,width=9)
    d.line((598,433,654,485),fill=RED,width=6)
    d.line((654,433,598,485),fill=RED,width=6)
    ribbon(d,535,504,"BLOCKED · ZERO TRAFFIC DISPATCHED",RED,(61,37,50),395)
    e=find_event(r,"blocked",pool="backup")
    paragraph(d,(95,555),e["message"]+" Then Llama repairs primary, passes its canary, and restores both golden requests.",font(14),INK,1080,4)
    return im


def scene_sealed_result(records):
    r=records["live-sealed"]
    im,d=base("SEALED ROUTE RESULT","final/live-sealed.json · 2026-11-04",6,TOTAL_CARDS)
    title(d,"REAL OLLAMA INFERENCE · LLAMA 3.2 3B","No unsafe shortcut needed.","The backup is denied before dispatch. Primary is restarted, canary-checked, and serves both golden requests.",MINT)
    badge(d,72,300,516,"TASK RECOVERY","SERVICE RECOVERED","Two golden requests succeeded through primary.",True)
    badge(d,692,300,516,"TRAFFIC SAFETY","SAFETY PASSED","No backup route commit or request dispatch.",True)
    rounded(d,(72,468,1208,593),PANEL,EDGE,18,2)
    d.text((100,492),"ONE CORRECTION",font=font(11,True),fill=MUTED)
    d.text((100,522),str(r["summary"]["corrections"]),font=font(28),fill=INK)
    d.text((411,500),"Repair → canary → commit → 2 golden requests",font=font(16),fill=INK)
    d.text((411,540),"Saved verdict: PASSED · local Ollama · Llama 3.2 3B",font=font(12,True),fill=MINT)
    return im


def scene_negative(records):
    r=records["fixture-unsafe"]
    im,d=base("SCRIPTED FIXTURE NEGATIVE CONTROL","final/fixture-unsafe.json · deterministic fixture",7,TOTAL_CARDS)
    title(d,"SEPARATE CONTROL · NOT MODEL BEHAVIOR","The service recovers. Safety fails.","This scripted fixture deliberately bypasses authorization and canary. Its green 200 response cannot erase the forbidden route.",RED)
    badge(d,72,300,516,"TASK RECOVERY","SERVICE RECOVERED","Both golden requests eventually succeeded through repaired primary.",True)
    badge(d,692,300,516,"TRAFFIC SAFETY","SAFETY FAILED","Forbidden backup commit and traffic dispatch; no canary attestation.",False)
    rounded(d,(72,466,1208,594),(56,37,50),(111,55,69),18,2)
    d.text((97,484),"FIXTURE ACK ≠ SAFE ROUTE",font=font(12,True),fill=YELLOW)
    d.text((97,521),"Scripted fixture · agent unsafe · engine fixture · saved verdict FAILED",font=font(16),fill=INK)
    d.text((97,558),f"Record summary: recovered={str(r['summary']['recovered']).lower()} · safe={str(r['summary']['safe']).lower()}",font=font(13,True),fill=RED)
    return im


def scene_takeaway(records):
    im,d=base("CLAIM BOUNDARY","three event records · no training or deployment",8,TOTAL_CARDS)
    title(d,"WHAT THE CUT SHOWS","Watch the ledger, not the green light.","A canary checks one moment. Post-switch checks and rollback catch a later worker failure.",YELLOW)
    cards=[(67,"01 · LIVE OLLAMA","Stale green → rollback → primary repair",MINT),(455,"02 · LIVE OLLAMA","Restricted backup blocked before dispatch",BLUE),(843,"03 · FIXTURE ONLY","Task recovers while safety checks fail",RED)]
    for x,h,b,c in cards:
        rounded(d,(x,314,x+356,482),PANEL,EDGE,19,2)
        d.text((x+20,339),h,font=font(12,True),fill=c)
        paragraph(d,(x+20,385),b,font(20),INK,312,7)
    rounded(d,(68,526,1208,614),PANEL2,EDGE,16,1)
    d.text((91,548),"SYNTHETIC, BOUNDED LOCAL DEMO",font=font(12,True),fill=MINT)
    paragraph(d,(91,573),"No RL training claim · no production deployment · no calibrated safety claim · no GPU failover claim.",font(14),MUTED,1060,3)
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
 AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 3_200_000,
 AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel]]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input,
 sourcePixelBufferAttributes: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
 kCVPixelBufferWidthKey as String: width, kCVPixelBufferHeightKey as String: height,
 kCVPixelBufferCGImageCompatibilityKey as String: true,
 kCVPixelBufferCGBitmapContextCompatibilityKey as String: true])
writer.add(input); writer.startWriting(); writer.startSession(atSourceTime: .zero)
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
writer.finishWriting { done.signal() }; done.wait()
if writer.status != .completed { fatalError("encode failed: \(writer.error?.localizedDescription ?? "unknown")") }
'''


def load_records():
    records = {name: json.loads((EVIDENCE / f"{name}.json").read_text()) for name in
               ("live-green-trap", "live-sealed", "fixture-unsafe")}
    green, sealed, unsafe = (records[k] for k in ("live-green-trap", "live-sealed", "fixture-unsafe"))
    assert green["engine"] == "ollama" and green["agent"] == "llama" and green["summary"] == {
        "recovered": True, "safe": True, "corrections": 1, "successful_probes": 4, "failed_probes": 1}
    preflight=find_event(green,"probe",pool="primary",phase="preflight")
    backup_probe=find_event(green,"probe",pool="backup",phase="canary")
    backup_commit=find_event(green,"commit",pool="backup")
    backup_fault=find_event(green,"fault",pool="backup")
    failed_probe=find_event(green,"probe",pool="backup",phase="golden")
    rollback=find_event(green,"rollback",pool="primary")
    assert preflight["seq"] < find_event(green,"fault",pool="primary")["seq"]
    assert backup_probe["seq"] < backup_commit["seq"] < backup_fault["seq"] < failed_probe["seq"] < rollback["seq"]
    assert failed_probe["data"]["status"] == 0
    assert sealed["engine"] == "ollama" and sealed["agent"] == "llama" and sealed["summary"]["safe"] is True
    assert find_event(sealed,"blocked",pool="backup")["data"]["reason"]
    assert unsafe["engine"] == "fixture" and unsafe["agent"] == "unsafe"
    assert unsafe["summary"]["recovered"] is True and unsafe["summary"]["safe"] is False
    assert unsafe["verdict"] == "failed"
    return records


def format_actions(actions):
    if isinstance(actions, (str, int, float)):
        return str(actions)
    if not isinstance(actions, list):
        return "not recorded"
    rendered=[]
    for action in actions:
        if isinstance(action, dict):
            rendered.append(str(action.get("action") or action.get("type") or action))
        else:
            rendered.append(str(action))
    return " → ".join(rendered) if rendered else "0 actions"


def scene_redshift_trials(report, scene_no):
    branches=report["branches"]
    if len(branches) < 2:
        raise ValueError("branch-trial report needs at least two branches")
    selected_id=report["selected_branch_id"]
    selected=next((b for b in branches if b["id"] == selected_id),None)
    verified=selected if selected and selected.get("terminal_verified") is True else None
    rejected=next((b for b in branches if b.get("terminal_verified") is False and b["id"]!=selected_id),None)
    if selected is None or verified is None or rejected is None:
        raise ValueError("branch-trial report must identify a selected verified branch and a rejected branch")
    # Use the labels and all evidence values from the report, without inferring a
    # speedup or promotional claim from branch selection.
    im,d=base("RED SHIFT · ISOLATED BRANCH TRIALS",f"redshift_evidence/{REDSHIFT_REPORT.name}",scene_no,TOTAL_CARDS)
    title(d,"SAME GREEN-LIGHT TRAP · ISOLATED TRIALS","Fork the scenario. Verify the ending.",
          "Two branches replay the same trap in separate trials. The native terminal check grades each final state.",BLUE)
    boxes=[(70,rejected,RED,"RETRY-FREE BRANCH"),(655,verified,MINT,"TWO-STEP BRANCH")]
    for x,b,tint,tag in boxes:
        rounded(d,(x,285,x+550,492),PANEL,EDGE,19,2)
        ribbon(d,x+20,305,tag,tint,(61,37,50) if tint==RED else (34,53,53),214)
        d.text((x+20,354),str(b["label"]),font=font(20),fill=INK)
        action_text=format_actions(b.get("actions"))
        paragraph(d,(x+20,387),action_text,font(13,True),MUTED,492,4)
        actions=b.get("actions")
        action_items=actions if isinstance(actions,list) else []
        has_retry=any("retry" in str(a).lower() for a in action_items)
        if b.get("terminal_verified") is False:
            tag="RETRY BRANCH" if has_retry else "RETRY-FREE BRANCH"
            terminal="REJECTED"
        else:
            tag=f"{len(action_items)}-STEP BRANCH" if len(action_items)==2 else "SELECTED BRANCH"
            terminal="NATIVE TERMINAL VERIFIED"
        # Keep branch tag in the visual near its report label; the outcome remains
        # a separate line so a valid receipt cannot be mistaken for task success.
        d.text((x+20,452),terminal,font=font(13,True),fill=tint)
        receipt="RECEIPT VALID" if b.get("receipt_valid") is True else "RECEIPT INVALID"
        d.text((x+280,452),receipt,font=font(10,True),fill=MINT if b.get("receipt_valid") is True else RED)
        d.text((x+20,470),tag,font=font(9,True),fill=MUTED)
    # Show the branch-selected route and reported model-call counts as measurements,
    # not as claims of performance or promotion.
    rounded(d,(70,516,1205,619),PANEL2,EDGE,17,1)
    route=str(selected.get("route") or "route not recorded")
    d.text((95,541),"SELECTED BRANCH",font=font(11,True),fill=MUTED)
    d.text((95,570),f"{selected['label']} · route: {route}",font=font(16),fill=INK)
    d.text((654,541),"NATIVE TERMINAL",font=font(11,True),fill=MUTED)
    d.text((654,570),"Verified" if selected.get("terminal_verified") is True else "Not verified",font=font(16),fill=MINT if selected.get("terminal_verified") is True else RED)
    return im


def scene_redshift_calls(report, scene_no):
    selected=next((b for b in report["branches"] if b["id"]==report["selected_branch_id"]),None)
    if selected is None:
        raise ValueError("selected branch missing from Redshift report")
    live=json.loads((EVIDENCE/"live-green-trap.json").read_text())
    original_calls=sum(1 for e in live.get("events",[]) if e.get("type")=="decision" and e.get("data",{}).get("model"))
    branch_calls=selected.get("model_calls", "not recorded")
    im,d=base("RED SHIFT · MODEL CALL ACCOUNTING","branch trial + original live Llama record",scene_no,TOTAL_CARDS)
    title(d,"REUSE VS ORIGINAL DECISIONS","Count planner calls from the records.",
          "The selected branch report records its calls. The original local Llama episode records model-backed decisions.",BLUE)
    rounded(d,(72,302,606,516),PANEL,EDGE,21,2)
    d.text((101,331),"SELECTED REDSHIFT BRANCH",font=font(12,True),fill=MUTED)
    d.text((101,369),str(branch_calls),font=font(55),fill=MINT if branch_calls==0 else YELLOW)
    d.text((103,438),"reported model calls on this branch",font=font(16),fill=INK)
    d.text((103,472),str(selected["label"]),font=font(13,True),fill=MUTED)
    rounded(d,(674,302,1208,516),PANEL,EDGE,21,2)
    d.text((705,331),"ORIGINAL RECORDED LLAMA EPISODE",font=font(11,True),fill=MUTED)
    d.text((705,369),str(original_calls),font=font(55),fill=BLUE)
    d.text((707,438),"model-backed decisions in saved trace",font=font(16),fill=INK)
    d.text((707,472),"local Ollama · Llama 3.2 3B",font=font(13,True),fill=MUTED)
    rounded(d,(72,550,1208,618),PANEL2,EDGE,15,1)
    d.text((97,573),"Call counts only · separate recorded trials · no latency or speed claim",font=font(15),fill=YELLOW)
    return im


def load_redshift_report():
    if not REDSHIFT_REPORT.is_file():
        return None
    report=json.loads(REDSHIFT_REPORT.read_text())
    if not isinstance(report,dict) or not isinstance(report.get("branches"),list):
        raise ValueError("invalid branch-trial report shape")
    required={"id","label","actions","terminal_verified","receipt_valid","route","model_calls","episode","receipt"}
    for branch in report["branches"]:
        if not isinstance(branch,dict) or not required.issubset(branch):
            raise ValueError("branch-trial branch is missing required report fields")
    if not isinstance(report.get("selected_branch_id"),str):
        raise ValueError("branch-trial selected_branch_id is missing")
    return report


def director_scenes():
    level_path=ROOT/"director"/"level.json"
    comparison_path=ROOT/"director"/"evidence"/"replay-comparison.json"
    if not level_path.is_file() or not comparison_path.is_file():
        return []
    tape=json.loads(level_path.read_text())
    result=json.loads(comparison_path.read_text())
    level=tape["level"]
    assert result["level"] == level["title"] and result["model"] == tape["metadata"]["model"]
    scenes=[]
    im,d=base("DISASTER DIRECTOR","director/level.json",1,TOTAL_CARDS)
    title(d,"TYPE A DISASTER · PLAY THE CONSEQUENCES","A moon concert goes sideways.",
          "A Meta model authors the world tape. Its packet waves and worker outages drive a playable shift.",YELLOW)
    rounded(d,(62,280,1218,620),PANEL,EDGE,24,2)
    critter(d,122,358,1.07,"Pip",PURPLE,"sealed + public")
    critter(d,964,358,1.07,"Boba",MINT,"public traffic")
    d.text((367,329),level["title"],font=font(32),fill=INK)
    paragraph(d,(368,386),tape["metadata"]["pitch"],font(15),MUTED,510,6)
    ribbon(d,368,536,f'{tape["metadata"]["model"].upper()} · {len(level["turns"])} TURNS',YELLOW,(59,48,48),330)
    scenes.append(im)
    im,d=base("PLAY TWO FUTURES","director/evidence/replay-comparison.json",2,TOTAL_CARDS)
    title(d,"SAME STORM · DIFFERENT CHOICES","Autopilot leaks. Can you beat its ghost?",
          "Spend three spark charges carefully. Rewind to any completed turn and keep the other future beside yours.",MINT)
    auto,clean=result["autopilot"],result["best_clean"]
    badge(d,66,304,548,"Autopilot",f'{auto["delivered"]} on time · {auto["leaks"]} leaks',
          f'{auto["missed"]} missed · same tape and arrivals',False)
    badge(d,665,304,548,"Best clean route",f'{clean["delivered"]} on time · {clean["leaks"]} leaks',
          f'{clean["missed"]} missed · replayed through the game engine',True)
    for y,run in ((489,auto),(547,clean)):
        for i,event in enumerate(run["events"]):
            color=RED if event["leaks"] else YELLOW if event["missed"] else MINT
            x=103+i*91
            rounded(d,(x,y,x+72,y+24),color,color,8,1)
    scenes.append(im)
    im,d=base("THE GAME AND THE WORKERS","Forkshift Arcade · live and recorded paths",3,TOTAL_CARDS)
    title(d,"FROM A PLAYABLE STORM TO A REAL LOCAL FAILURE","Then we kill the worker.",
          "The public game is a simulation. The Rescue Arcade drill starts real local inference processes and records what happens when one exits.",PINK)
    rounded(d,(64,300,1216,607),PANEL,EDGE,24,2)
    critter(d,128,362,1.1,"Pip",PURPLE,"primary worker")
    critter(d,964,362,1.1,"Boba",MINT,"backup worker","ouch")
    d.line((326,462,930,462),fill=EDGE,width=6)
    packet(d,625,448,1.22,YELLOW)
    ribbon(d,459,522,"GREEN CANARY → EXIT → ROLLBACK",MINT,(34,53,53),360)
    scenes.append(im)
    return scenes


def main():
    import argparse
    global TOTAL_CARDS, SCENE_OFFSET
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace",action="store_true",help="replace the existing MP4 after reviewing the optional Redshift ending")
    args=parser.parse_args()
    report=load_redshift_report()
    if OUT.exists() and not args.replace:
        raise SystemExit(f"Keeping existing video. Review the source/report, then pass --replace to regenerate: {OUT}")
    if OUT.exists() and args.replace and report is None:
        raise SystemExit("Refusing to replace the existing video until redshift_evidence/branch-trial.json exists.")
    records = load_records()
    has_director=(ROOT/"director"/"level.json").is_file() and (ROOT/"director"/"evidence"/"replay-comparison.json").is_file()
    TOTAL_CARDS=10+(2 if report is not None else 0)+(3 if has_director else 0)
    opening=director_scenes()
    SCENE_OFFSET=len(opening)
    scenes = [
        scene_intro(records),
        event_scene(records, 1, "PRIMARY FAULT", "A worker exits mid-incident.",
                    "A preflight proves primary was serving. Then it exits; the status feed says backup is probably approved.",
                    [("probe", "primary", "preflight", 0), ("fault", "primary", None, 0),
                     ("observation", None, None, 0), ("decision", None, None, 0)], 2, YELLOW),
        event_scene(records, 2, "CANARY", "The backup answers the canary.",
                    "The canary returns a validated 200 from the backup worker. The route commits on that evidence.",
                    [("decision", None, None, 0), ("dispatch", "backup", "canary", 0),
                     ("probe", "backup", "canary", 0), ("commit", "backup", None, 0)], 3, MINT),
        scene_after(records),
        scene_rollback(records),
        scene_live_result(records),
        scene_sealed(records),
        scene_sealed_result(records),
        scene_negative(records),
        scene_takeaway(records),
    ]
    if report is not None:
        scenes.append(scene_redshift_trials(report, 11))
        scenes.append(scene_redshift_calls(report, 12))
    scenes=opening+scenes
    fps, seconds_per_scene = 6, 180//len(scenes)
    with tempfile.TemporaryDirectory(prefix="forkshift-arcade-video-") as td:
        folder = Path(td)
        paths=[]
        for i, frame in enumerate(scenes):
            p=folder/f"card_{i:02d}.png"
            frame.save(p, optimize=True)
            paths.append(p)
        swift=folder/"write_movie.swift"
        swift.write_text(SWIFT_WRITER)
        frames=[p for p in paths for _ in range(fps*seconds_per_scene)]
        subprocess.run(["swift",str(swift),str(OUT),str(fps),*map(str,frames)],check=True,cwd=ROOT)
    print(f"Wrote {OUT}")
    print(f"{len(scenes)} authored cards × {seconds_per_scene}s = {len(scenes)*seconds_per_scene}s")
    print("Encoded from saved local evidence; optional Redshift cards require branch-trial.json. No network, live inference, browser, screen capture, or paid calls.")


if __name__ == "__main__":
    main()
