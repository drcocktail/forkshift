#!/usr/bin/env python3
"""Synthesize local narration and mux it into Forkshift-Narrated.mp4.

Prefers local Kokoro-ONNX when installed and model/voice files are present.
Falls back to macOS Samantha via `say` only if neural setup/inference fails.
All synthesis is local; there are no cloud/API calls. Model assets stay outside
this project. Optional custom paths are accepted via flags or environment vars.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parent
INPUT=ROOT/"Forkshift-Rescue-Arcade.mp4"
NARRATION=ROOT/"narration.json"
OUTPUT=ROOT/"Forkshift-Narrated.mp4"
CAPTIONS=ROOT/"Forkshift-Narrated.vtt"
FPS=6
VIDEO_FRAMES=1080
SR=24000

SWIFT_MUX=r'''import AVFoundation
import CoreMedia
import Foundation
func fail(_ s:String)->Never { fputs(s+"\n",stderr); exit(1) }
let a=CommandLine.arguments
guard a.count==4 else { fail("usage: mux.swift input.mp4 narration.wav output.mp4") }
let input=AVURLAsset(url:URL(fileURLWithPath:a[1]))
let audio=AVURLAsset(url:URL(fileURLWithPath:a[2]))
let output=URL(fileURLWithPath:a[3])
let duration=try await input.load(.duration)
guard abs(CMTimeGetSeconds(duration)-180.0)<0.1 else { fail("source video must be 180 seconds") }
guard let videoTrack=try await input.loadTracks(withMediaType:.video).first,
      let audioTrack=try await audio.loadTracks(withMediaType:.audio).first else { fail("missing video/audio track") }
guard CMTimeGetSeconds(try await audio.load(.duration)) >= CMTimeGetSeconds(duration)-0.02 else { fail("narration is shorter than the video") }
let comp=AVMutableComposition()
guard let v=comp.addMutableTrack(withMediaType:.video,preferredTrackID:kCMPersistentTrackID_Invalid),
      let s=comp.addMutableTrack(withMediaType:.audio,preferredTrackID:kCMPersistentTrackID_Invalid) else { fail("cannot create mux tracks") }
try v.insertTimeRange(CMTimeRange(start:.zero,duration:duration),of:videoTrack,at:.zero)
try s.insertTimeRange(CMTimeRange(start:.zero,duration:duration),of:audioTrack,at:.zero)
v.preferredTransform=try await videoTrack.load(.preferredTransform)
guard let exporter=AVAssetExportSession(asset:comp,presetName:AVAssetExportPresetHighestQuality), exporter.supportedFileTypes.contains(.mp4) else { fail("MP4 export is unavailable") }
exporter.outputURL=output; exporter.outputFileType = .mp4; exporter.shouldOptimizeForNetworkUse=true
try await exporter.export()
guard exporter.status == .completed else { fail("mux failed: \(exporter.error?.localizedDescription ?? "unknown")") }
let final=AVURLAsset(url:output)
let finalDuration=CMTimeGetSeconds(try await final.load(.duration))
let video=try await final.loadTracks(withMediaType:.video)
let voice=try await final.loadTracks(withMediaType:.audio)
guard abs(finalDuration-180.0)<0.1 && !video.isEmpty && !voice.isEmpty else { fail("final duration or tracks are invalid") }
print(String(format:"Mux verified: %.3f sec · %d video track · %d audio track",finalDuration,video.count,voice.count))
'''

def scene_lengths(n):
    q,r=divmod(VIDEO_FRAMES,n)
    return [q+(i<r) for i in range(n)]

def ts(t):
    ms=round(t*1000); hh,ms=divmod(ms,3600000); mm,ms=divmod(ms,60000); ss,ms=divmod(ms,1000)
    return f"{hh:02}:{mm:02}:{ss:02}.{ms:03}"

def fit_audio(audio,sr,limit):
    """If necessary, modestly compress speech duration with linear resampling."""
    audio=np.asarray(audio,dtype=np.float32).reshape(-1)
    if len(audio)/sr>limit:
        ratio=(len(audio)/sr)/limit
        if ratio>1.22: raise RuntimeError(f"speech needs {ratio:.2f}x speed-up; exceeds natural cap")
        target=max(1,int(len(audio)/ratio))
        old=np.linspace(0,1,len(audio),endpoint=False,dtype=np.float32)
        new=np.linspace(0,1,target,endpoint=False,dtype=np.float32)
        audio=np.interp(new,old,audio).astype(np.float32)
    fade=min(int(sr*.012),len(audio)//4)
    if fade:
        audio[:fade]*=np.linspace(0,1,fade,dtype=np.float32)
        audio[-fade:]*=np.linspace(1,0,fade,dtype=np.float32)
    peak=float(np.max(np.abs(audio))) if len(audio) else 0
    if peak>.94: audio*=.94/peak
    return audio

def kokoro_create(text,tts,voice,speed):
    audio,sr=tts.create(text,voice=voice,speed=speed,lang="en-us")
    audio=np.asarray(audio,dtype=np.float32).reshape(-1)
    if not len(audio): raise RuntimeError("Kokoro returned empty audio")
    if sr!=SR:
        # Linear resampling is adequate for this short speech-only track.
        target=max(1,round(len(audio)*SR/sr))
        audio=np.interp(np.linspace(0,1,target,endpoint=False),np.linspace(0,1,len(audio),endpoint=False),audio).astype(np.float32)
        sr=SR
    return audio,sr

def mac_say(text,work,index,voice,rate):
    aiff=work/f"say_{index:02}.aiff"; wav=work/f"say_{index:02}.wav"
    subprocess.run(["/usr/bin/say","-v",voice,"-r",str(rate),"-o",str(aiff),text],check=True)
    subprocess.run(["/usr/bin/afconvert","-f","WAVE","-d",f"LEI16@{SR}","-c","1",str(aiff),str(wav)],check=True)
    audio,sr=sf.read(wav,dtype="float32",always_2d=False)
    if audio.ndim>1: audio=audio.mean(axis=1)
    return np.asarray(audio,dtype=np.float32),int(sr)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model",type=Path,default=Path(os.getenv("KOKORO_MODEL",Path.home()/".cache/forkshift-kokoro/kokoro-v1.0.onnx")),help="local Kokoro ONNX file")
    ap.add_argument("--voices",type=Path,default=Path(os.getenv("KOKORO_VOICES",Path.home()/".cache/forkshift-kokoro/voices-v1.0.bin")),help="local Kokoro voice pack")
    ap.add_argument("--voice",default="af_sarah",help="Kokoro voice name")
    ap.add_argument("--speed",type=float,default=1.04)
    ap.add_argument("--fallback-voice",default="Samantha",help="macOS say voice used only if Kokoro fails")
    ap.add_argument("--fallback-rate",type=int,default=178)
    ap.add_argument("--replace",action="store_true",help="replace existing narrated video/captions")
    args=ap.parse_args()
    if not INPUT.is_file(): raise SystemExit(f"Missing input video: {INPUT}")
    if not NARRATION.is_file(): raise SystemExit(f"Missing narration script: {NARRATION}")
    if (OUTPUT.exists() or CAPTIONS.exists()) and not args.replace:
        raise SystemExit("Output already exists; use --replace after reviewing it.")
    data=json.loads(NARRATION.read_text()); scenes=data.get("scenes")
    if not isinstance(scenes,list) or len(scenes)!=16 or any(not isinstance(s,dict) or not s.get("id") or not s.get("text") for s in scenes):
        raise SystemExit("narration.json must have 16 scenes with id and text")
    counts=scene_lengths(len(scenes)); assert sum(counts)==VIDEO_FRAMES
    durations=[c/FPS for c in counts]

    engine="Kokoro-ONNX"; voice=args.voice; tts=None; error=None
    if args.model.is_file() and args.voices.is_file():
        try:
            from kokoro_onnx import Kokoro
            tts=Kokoro(str(args.model),str(args.voices))
            kokoro_create("Local model ready.",tts,voice,args.speed)
        except Exception as exc:
            error=f"{type(exc).__name__}: {exc}"; tts=None
    else: error="local model or voices file is missing"
    if tts is None:
        if not shutil.which("say") or not shutil.which("afconvert"):
            raise SystemExit(f"Kokoro unavailable ({error}); macOS say fallback unavailable")
        engine="macOS say fallback"; voice=args.fallback_voice

    with tempfile.TemporaryDirectory(prefix="forkshift-narration-") as td:
        work=Path(td); mix=np.zeros(VIDEO_FRAMES*SR//FPS,dtype=np.float32); cues=[]; cursor=0
        for i,(scene,slot) in enumerate(zip(scenes,durations)):
            text=str(scene["text"]).strip()
            try:
                if tts is not None:
                    audio,sr=kokoro_create(text,tts,args.voice,args.speed)
                else:
                    audio,sr=mac_say(text,work,i,args.fallback_voice,args.fallback_rate)
                audio=fit_audio(audio,sr,slot-.5)
            except Exception as exc:
                if tts is not None:
                    # Keep one consistent provider across the whole video if neural setup fails.
                    raise RuntimeError(f"Kokoro failed on scene {scene['id']}: {exc}") from exc
                raise
            start=cursor/FPS+.30; start_sample=round(start*SR); stop=start_sample+len(audio)
            if stop>len(mix): raise RuntimeError(f"{scene['id']} audio exceeds video duration")
            mix[start_sample:stop]=audio
            end=start+len(audio)/SR
            cues.append((start, end, text))
            print(f"{i+1:02d}/16 {scene['id']}: {len(audio)/SR:.2f}s voice / {slot:.2f}s scene")
            cursor+=counts[i]
        if float(np.max(np.abs(mix)))<.001: raise SystemExit("Narration mix is silent")
        wav=work/"narration.wav"; sf.write(wav,mix,SR,subtype="PCM_16")
        swift=work/"mux.swift"; swift.write_text(SWIFT_MUX)
        subprocess.run(["swift",str(swift),str(INPUT),str(wav),str(OUTPUT)],check=True,cwd=ROOT)
    vtt = ["WEBVTT", ""]
    for start, end, text in cues:
        vtt.extend((f"{ts(start)} --> {ts(end)}", text, ""))
    CAPTIONS.write_text("\n".join(vtt), encoding="utf-8")
    print(f"Provider: {engine}; voice: {voice}; output: {OUTPUT}")
    print(f"Captions: {CAPTIONS}")
    if error: print(f"Fallback reason: {error}")

if __name__=="__main__": main()
