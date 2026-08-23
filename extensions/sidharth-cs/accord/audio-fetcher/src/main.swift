// Audio Fetcher — Live Bridge to existing /audio endpoint.
// Captures Zoom remote audio (ScreenCaptureKit) + local mic (AVAudioEngine),
// segments into 2s chunks, POSTs to backend /audio for Groq transcription.
//
// Build: swiftc -o ../build/audiofetcher main.swift \
//   -framework ScreenCaptureKit -framework CoreMedia -framework Foundation \
//   -framework AppKit -framework AVFoundation
//
// Usage: ./audiofetcher --uuid <meeting-uuid> [--backend http://localhost:8010] [--seconds 300] [--mic]

import Foundation
import ScreenCaptureKit
import CoreMedia
import AppKit
import AVFoundation

func now() -> String { let f = DateFormatter(); f.dateFormat = "HH:mm:ss.SSS"; return f.string(from: Date()) }
func log(_ msg: String) { print("[\(now())] \(msg)"); fflush(stdout) }

// ---- base64url encoding (matches frontend useMeetingSession.js) -------------
func base64urlEncode(_ s: String) -> String {
    return Data(s.utf8).base64EncodedString()
        .replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_")
        .trimmingCharacters(in: CharacterSet(charactersIn: "="))
}

// ---- Chunk sender: buffers Int16 PCM, POSTs every 6s to backend -------------
class AudioChunkSender {
    let backendURL: URL
    let meetingUUID: String
    // samples per chunk (6s at 48k = 288000). Was 4s (192000) — each chunk
    // is transcribed by Whisper as a fully independent request with zero
    // context from its neighbor, so a short window forces it to "complete"
    // whatever word/number got cut off into a plausible-but-wrong whole
    // one ("modern response." / "October 3rd.") instead of correctly
    // continuing mid-word. Confirmed directly: the same audio run through
    // Whisper large-v3 on console.groq.com (which sends much larger,
    // naturally-bounded segments, not fixed 4s slices) came back clean —
    // same model, different chunking, night-and-day result. 6s trades a
    // few seconds of panel latency for meaningfully more context per call;
    // the batcher's own silence-gap/max-wait (2-3s) already means the
    // document wasn't updating on every single 4s chunk anyway.
    let chunkSize: Int
    // Samples of the PREVIOUS chunk replayed at the head of the next one
    // (1.5s at 48k). Whisper transcribes every chunk as an independent
    // request, so a word straddling a boundary gets guessed at from half
    // its audio — "October 30th" split across two calls came back as
    // "October 3rd." then "30th.", and "existing domain" became "existing
    // products." Replaying the tail means the boundary word is whole
    // inside at least one request. The backend strips the repeated words
    // from the transcript (see _dedupe_overlap in routes_audio.py).
    let overlapSize: Int
    let sampleRate: Int
    let minSignalRMS: Float   // skip silence below this RMS
    var buffer: [Int16] = []
    // Tail of the last emitted chunk, prepended to the next one.
    var overlapTail: [Int16] = []
    let lock = NSLock()
    var chunkCount = 0
    var sentCount = 0
    var failCount = 0
    var lastLatency: Double = 0
    let sendQueue = DispatchQueue(label: "audio-sender")

    // A chunk ends at a PAUSE when there is one, and at chunkSize only when
    // the speaker has not drawn breath for that long. Fixed slices cut mid
    // sentence, and Whisper does not return a half sentence — it invents an
    // ending for the audio it was handed. Measured against the committed
    // 77s SOW audio, transcribing each strategy's chunks directly:
    //
    //   fixed 6s   13 chunks, 9 cut mid-sentence, invented endings
    //              ("...add items to a cart, and complete the process.")
    //   fixed 10s   8 chunks, worse still — one came back with no
    //              punctuation and spelled-out numbers ("forty five
    //              thousand dollars actually no make it fifty five
    //              thousand"), which the money classifier cannot read
    //   pause-bounded, 12s ceiling
    //               9 chunks, ZERO cut mid-sentence, no invented endings,
    //               "October 30th" and "$45,000"/"$55,000" all intact
    //
    // Longer chunks alone make it WORSE. It is where the boundary falls
    // that matters, not how much audio is in it.
    let minChunkSize: Int       // never end a chunk shorter than this
    let silenceTail: Int        // trailing samples inspected for a pause
    let silenceAmplitude: Int16 // |sample| below this counts as silence

    init(backendURL: URL, meetingUUID: String, chunkSize: Int = 576000, sampleRate: Int = 48000, minSignalRMS: Float = 0.008, overlapSize: Int = 72000, minChunkSize: Int = 144000, silenceTail: Int = 28800, silenceAmplitude: Int16 = 500) {
        self.backendURL = backendURL
        self.meetingUUID = meetingUUID
        self.chunkSize = chunkSize
        self.sampleRate = sampleRate
        self.minSignalRMS = minSignalRMS
        self.overlapSize = overlapSize
        self.minChunkSize = minChunkSize
        self.silenceTail = silenceTail
        self.silenceAmplitude = silenceAmplitude
    }

    /// True when the buffer's last `silenceTail` samples are all quiet —
    /// the speaker has paused, so the chunk can end on a whole phrase.
    /// Caller holds `lock`.
    private func endsOnAPause() -> Bool {
        guard buffer.count >= minChunkSize else { return false }
        for s in buffer.suffix(silenceTail) where abs(Int(s)) >= Int(silenceAmplitude) {
            return false
        }
        return true
    }

    func append(_ sample: Int16) {
        lock.lock()
        buffer.append(sample)
        // chunkSize is a CEILING now, not the trigger. The pause is the
        // trigger; the ceiling only fires when someone talks straight
        // through it, so a room with constant background noise degrades to
        // exactly the fixed-slice behaviour this replaced — never worse.
        if buffer.count >= chunkSize || endsOnAPause() {
            // Send the previous chunk's tail ahead of this one so any word
            // spanning the boundary is heard whole at least once.
            let chunk = overlapTail + buffer
            overlapTail = Array(buffer.suffix(overlapSize))
            buffer.removeAll(keepingCapacity: true)
            chunkCount += 1
            lock.unlock()
            send(chunk)
        } else {
            lock.unlock()
        }
    }

    private func send(_ chunk: [Int16]) {
        sendQueue.async { [self] in
            // Compute RMS to skip silence
            var sq: Double = 0
            for s in chunk { let v = Double(s) / 32767.0; sq += v * v }
            let rms = Float(sqrt(sq / Double(chunk.count)))
            guard rms > minSignalRMS else {
                log("  skip silent chunk (\(chunk.count) smp, rms=\(String(format:"%.4f",rms)))")
                return
            }
            let payload: [String: Any] = ["samples": chunk, "sample_rate": self.sampleRate]
            guard let body = try? JSONSerialization.data(withJSONObject: payload) else { log("  JSON error"); return }

            var request = URLRequest(url: self.backendURL)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
            request.timeoutInterval = 30

            // Bounded client-side retry for the backend's transient 503
            // (Groq rate-limit exhaustion, never ingested). A 503 means the
            // chunk was NOT transcribed, so re-sending it cannot duplicate a
            // transcript event; ordering is preserved because this loop holds
            // the serial send-queue slot. Other non-2xx remain permanent drops.
            let maxAttempts = 3
            for attempt in 0..<maxAttempts {
                let start = Date()
                let sem = DispatchSemaphore(value: 0)
                var outData: Data? = nil
                var status = 0
                var outErr: Error? = nil
                URLSession.shared.dataTask(with: request) { data, response, error in
                    outData = data
                    outErr = error
                    status = (response as? HTTPURLResponse)?.statusCode ?? 0
                    sem.signal()
                }.resume()
                sem.wait()  // serialize sends — preserves chronological order

                let elapsed = Date().timeIntervalSince(start)
                self.lastLatency = elapsed
                if let error = outErr {
                    self.failCount += 1
                    log("  POST FAILED (\(elapsed)s): \(error.localizedDescription)")
                    return
                }
                if status == 503 && attempt < maxAttempts - 1 {
                    log("  POST 503 transient — retry \(attempt + 1)/\(maxAttempts) (not ingested, safe to resend)")
                    Thread.sleep(forTimeInterval: 1.0)
                    continue
                }
                if status != 200 {
                    self.failCount += 1
                    let bodyStr = outData.flatMap { String(data: $0, encoding: .utf8) } ?? ""
                    log("  POST HTTP \(status) (\(elapsed)s): \(bodyStr.prefix(120))")
                    return
                }
                self.sentCount += 1
                let text = outData.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }?["text"] as? String ?? ""
                log("  → chunk #\(self.sentCount) transcribed (\(String(format:"%.1f",elapsed))s): \(text.prefix(80))")
                return
            }
            // Bounded 503 retries exhausted — record explicitly, never as a
            // normal success (sentCount is untouched, so no duplicate event).
            self.failCount += 1
            log("  POST 503 retries exhausted for a chunk — dropped explicitly")
        }
    }

    func summary() -> String {
        return "chunks=\(chunkCount) sent=\(sentCount) failed=\(failCount) lastLat=\(String(format:"%.1f",lastLatency))s"
    }

    // Flush any partial buffer (fewer than chunkSize samples) so a STOP
    // doesn't silently drop the tail of the capture. Sends on the same
    // serial sendQueue, so ordering is preserved.
    func flush() {
        lock.lock()
        if !buffer.isEmpty {
            // Same overlap as a normal chunk — the final utterance is the
            // one most likely to be cut mid-word by a STOP.
            let chunk = overlapTail + buffer
            overlapTail = []
            buffer.removeAll(keepingCapacity: true)
            chunkCount += 1
            lock.unlock()
            send(chunk)
        } else {
            lock.unlock()
        }
    }

    // Block until every queued send has completed — used on STOP so the
    // process doesn't exit with an in-flight upload still on the wire.
    func waitUntilIdle() {
        sendQueue.sync {}
    }
}

// ---- Remote audio delegate (ScreenCaptureKit) -------------------------------
class AudioDelegate: NSObject, SCStreamOutput, SCStreamDelegate {
    var callbacks = 0; var inspected = 0; var formatPrinted = false
    var totalSamples: UInt64 = 0
    var peakAbs: Float = 0
    var emptyBuffers = 0
    var noFormatDesc = 0
    var ablFallback = 0        // ABL fill failed, CMBlockBuffer fallback succeeded
    var extractionFailures = 0 // genuine failures (fallback also produced nothing)
    var lastExtractStatus: OSStatus = 0
    var fallbackStatus: OSStatus = 0  // ABL status that triggered fallback
    var sender: AudioChunkSender? = nil

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        callbacks += 1

        guard let desc = CMSampleBufferGetFormatDescription(sb),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc)?.pointee else {
            noFormatDesc += 1
            if noFormatDesc <= 3 { log("  NO FORMAT DESC (cb#\(callbacks)) — empty audio callback") }
            return
        }
        let isFloat = (asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0
        let isNonInterleaved = (asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0
        let ch = Int(asbd.mChannelsPerFrame)
        let bps = Int(asbd.mBitsPerChannel / 8)

        if !formatPrinted {
            formatPrinted = true
            log("ASBD: \(isFloat ? "Float":"Int")\(asbd.mBitsPerChannel)bit \(Int(asbd.mSampleRate))Hz \(ch)ch nonInterleaved=\(isNonInterleaved ? "Y":"N")")
        }

        var extractedAny = false

        // AudioBufferList path (non-interleaved)
        var blSize = 0
        let s1 = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sb, bufferListSizeNeededOut: &blSize, bufferListOut: nil,
            bufferListSize: 0, blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: nil)
        if s1 == noErr && blSize > 0 {
            let raw = UnsafeMutablePointer<UInt8>.allocate(capacity: blSize)
            let blPtr = raw.withMemoryRebound(to: AudioBufferList.self, capacity: 1) { $0 }
            let s2 = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
                sb, bufferListSizeNeededOut: nil, bufferListOut: blPtr,
                bufferListSize: blSize, blockBufferAllocator: nil,
                blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: nil)
            if s2 == noErr {
                let nb = Int(blPtr.pointee.mNumberBuffers)
                for bi in 0..<nb {
                    let b = withUnsafePointer(to: &blPtr.pointee.mBuffers) {
                        $0.withMemoryRebound(to: AudioBuffer.self, capacity: nb) { $0[bi] }
                    }
                    guard let d = b.mData, b.mDataByteSize > 0 else {
                        emptyBuffers += 1
                        if emptyBuffers <= 3 { log("  EMPTY BUFFER (cb#\(callbacks) buf#\(bi))") }
                        continue
                    }
                    let n = Int(b.mDataByteSize) / bps
                    totalSamples &+= UInt64(n)
                    extractedAny = true
                    if isFloat && bps == 4 {
                        let fp = d.bindMemory(to: Float.self, capacity: n)
                        for i in 0..<n {
                            let s = fp[i]
                            if s.isNaN || s.isInfinite { continue }
                            peakAbs = max(peakAbs, abs(s))
                            sender?.append(Int16(max(-1, min(1, s)) * 32767))
                        }
                    }
                }
            } else {
                // ABL fill failed — record for diagnostics, fall back below.
                fallbackStatus = s2
                if ablFallback == 0 {
                    log("  ABL fill unavailable: OSStatus=\(s2) (0x\(String(s2, radix: 16))) — using CMBlockBuffer fallback")
                }
            }
            raw.deallocate()
        } else {
            if s1 != noErr && s1 != -12731 { // -12731 = kCMSampleBufferError_NotReady
                extractionFailures += 1
                lastExtractStatus = s1
                if extractionFailures <= 3 {
                    log("  ABL SIZE QUERY FAILED (cb#\(callbacks)): OSStatus=\(s1) (0x\(String(s1, radix: 16)))")
                }
            }
        }

        // If ABL extraction produced nothing, fall back to data pointer.
        // A successful fallback is a legitimate extraction — count as ablFallback.
        if !extractedAny {
            guard let bb = sb.dataBuffer else {
                extractionFailures += 1
                lastExtractStatus = -99999 // sentinel: no data buffer
                if extractionFailures <= 3 { log("  NO DATA BUFFER (cb#\(callbacks))") }
                return
            }
            var len = 0; var ptr: UnsafeMutablePointer<Int8>? = nil
            let dpStatus = CMBlockBufferGetDataPointer(bb, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &len, dataPointerOut: &ptr)
            guard dpStatus == noErr, let p = ptr, len > 0 else {
                extractionFailures += 1
                lastExtractStatus = dpStatus
                if extractionFailures <= 3 { log("  DATA POINTER FAILED (cb#\(callbacks)): OSStatus=\(dpStatus)") }
                return
            }
            let perChannel = isNonInterleaved ? len / (bps * ch) : len / bps
            if perChannel > 0 {
                ablFallback += 1
            }
            totalSamples &+= UInt64(perChannel)
            if isFloat && bps == 4 {
                let fp = p.withMemoryRebound(to: Float.self, capacity: perChannel) { $0 }
                for i in 0..<perChannel {
                    let s = fp[i]
                    if s.isNaN || s.isInfinite { continue }
                    peakAbs = max(peakAbs, abs(s))
                    sender?.append(Int16(max(-1, min(1, s)) * 32767))
                }
            }
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        log("STREAM ERROR: \(error.localizedDescription)")
    }
}

// ---- Mic capture (AVAudioEngine) --------------------------------------------
class MicCapture {
    var totalSamples: UInt64 = 0; var callbacks = 0; var started = false
    var peakAbs: Float = 0
    var sender: AudioChunkSender? = nil
    private let engine = AVAudioEngine()
    private let hwRate: Float

    init?() {
        let fmt = engine.inputNode.inputFormat(forBus: 0)
        hwRate = Float(fmt.sampleRate)
        guard hwRate > 0 else { return nil }
    }

    func start() {
        let downsample = hwRate / 48000.0  // mic → 48k to share sender chunk size
        engine.inputNode.installTap(onBus: 0, bufferSize: 4096, format: nil) { [weak self] buf, _ in
            guard let self = self, let ch = buf.floatChannelData else { return }
            self.callbacks += 1
            let frames = Int(buf.frameLength); let data = ch[0]
            var idx: Float = 0
            while Int(idx) < frames {
                let s = data[Int(idx)]
                if !s.isNaN && !s.isInfinite {
                    self.peakAbs = max(self.peakAbs, abs(s))
                    self.totalSamples &+= 1
                    self.sender?.append(Int16(max(-1, min(1, s)) * 32767))
                }
                idx += downsample
            }
        }
        do { try engine.start(); started = true }
        catch { log("Mic ERROR: \(error.localizedDescription)") }
    }

    func stop() { if started { engine.stop(); started = false } }
}

// ---- Thread-safe stop flag for SIGTERM/SIGINT ------------------------------
final class StopFlag {
    private let lock = NSLock()
    private var _value = false
    var value: Bool {
        get { lock.lock(); defer { lock.unlock() }; return _value }
        set { lock.lock(); _value = newValue; lock.unlock() }
    }
}

// ---- Main -------------------------------------------------------------------
var backendURLStr = "http://localhost:8010"
// Retained across the window-selection closure so the SIGTERM/SIGINT sources
// stay alive for the whole capture (a released source cancels silently).
var stopFlag: StopFlag? = nil
var retainedTermSource: DispatchSourceSignal? = nil
var retainedIntSource: DispatchSourceSignal? = nil
var meetingUUID = ""
var captureSecs = 300
var enableMic = false
var listMode = false
var dumpAppsMode = false
var appFilterMode = false

var args = Array(CommandLine.arguments.dropFirst())
while !args.isEmpty {
    let a = args.removeFirst()
    switch a {
    case "--backend": backendURLStr = args.removeFirst()
    case "--uuid": meetingUUID = args.removeFirst()
    case "--seconds": captureSecs = Int(args.removeFirst()) ?? 300
    case "--mic": enableMic = true
    case "--list": listMode = true
    case "--dump-apps": dumpAppsMode = true
    case "--app-filter": appFilterMode = true
    default: log("Unknown arg: \(a)")
    }
}

// Diagnostic modes (--app-filter, --list, --dump-apps) run standalone and do
// NOT require --uuid or --backend.
if appFilterMode || listMode || dumpAppsMode {
    log("=== Audio Fetcher — Diagnostic Mode ===")
} else {
    guard !meetingUUID.isEmpty else {
        log("ERROR: --uuid <meeting-uuid> required")
        log("Usage: ./audiofetcher --uuid <uuid> [--backend http://localhost:8010] [--seconds N] [--mic]")
        log("       ./audiofetcher --app-filter   (30s Zoom-app audio diagnostic)")
        exit(1)
    }
}

// Normalize backend URL (strip trailing slash)
while backendURLStr.hasSuffix("/") { backendURLStr.removeLast() }
let encodedUUID = base64urlEncode(meetingUUID)
let audioURL = URL(string: "\(backendURLStr)/api/meetings/\(encodedUUID)/audio")!
log("=== Audio Fetcher — Live Bridge ===")
log("Meeting UUID: \(meetingUUID)")
log("Encoded: \(encodedUUID)")
log("Backend: \(audioURL.absoluteString)")
log("Capture: \(captureSecs)s mic=\(enableMic ? "on" : "off")")

_ = NSApplication.shared
var retainedStream: SCStream? = nil
var retainedDelegate: AudioDelegate? = nil

DispatchQueue.main.async {
    SCShareableContent.getWithCompletionHandler { content, error in
        guard let content = content else { log("ERROR: \(error!)"); exit(1) }

        if listMode {
            log("=== ALL APPLICATIONS ===")
            for a in content.applications {
                log("  \(a.bundleIdentifier) \"\(a.applicationName)\" PID=\(a.processID)")
            }
            log("=== ZOOM-RELATED WINDOWS (all on-screen for any Zoom PID) ===")
            for w in content.windows where w.isOnScreen && w.frame.width > 0 && w.frame.height > 0 {
                if w.owningApplication?.bundleIdentifier == "us.zoom.xos" || (w.title ?? "").lowercased().contains("zoom") {
                    log("  id=\(w.windowID) \(Int(w.frame.width))x\(Int(w.frame.height)) bundle=\(w.owningApplication?.bundleIdentifier ?? "?") title=\"\(String((w.title ?? "").prefix(80)))\"")
                }
            }
            exit(0)
        }

        if appFilterMode {
            // Application-scoped filter: target us.zoom.xos by bundle ID
            let zoomApps = content.applications.filter { $0.bundleIdentifier == "us.zoom.xos" }
            guard let zoomApp = zoomApps.first, let display = content.displays.first else {
                log("ERROR: Zoom app not found or no display"); exit(1)
            }
            log("App-filter target: \(zoomApp.applicationName) PID=\(zoomApp.processID) bundle=\(zoomApp.bundleIdentifier)")
            log("Display: \(Int(display.width))x\(Int(display.height))")
            log("=== APP-SCOPED CAPTURE TEST (30s, no Groq) ===")

            let del = AudioDelegate()
            del.sender = nil  // no Groq for this test — audio diagnostics only
            let filter = SCContentFilter(display: display, including: [zoomApp], exceptingWindows: [])
            let cfg = SCStreamConfiguration()
            cfg.width = 2; cfg.height = 2; cfg.pixelFormat = kCVPixelFormatType_32BGRA
            cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1); cfg.showsCursor = false
            cfg.capturesAudio = true; cfg.sampleRate = 48000; cfg.channelCount = 2

            let stream = SCStream(filter: filter, configuration: cfg, delegate: del)
            try! stream.addStreamOutput(del, type: .audio, sampleHandlerQueue: .global())
            stream.startCapture()
            log("App-scoped capture started. Play the ElevenLabs MP3 now. 30s timer.")

            DispatchQueue.global().async {
                for i in 1...30 {
                    sleep(1)
                    if i % 5 == 0 {
                        let pk = del.peakAbs > 0.000001 ? 20.0 * log10(Double(del.peakAbs)) : -100.0
                        log("  [\(String(format:"%2d",i))s] cbs=\(del.callbacks) samples=\(del.totalSamples) emptyBufs=\(del.emptyBuffers) noFmt=\(del.noFormatDesc) pk=\(String(format:"%.0f",pk))dBFS")
                    }
                }
                stream.stopCapture()
                let pk = del.peakAbs > 0.000001 ? 20.0 * log10(Double(del.peakAbs)) : -100.0
                log("=== APP-FILTER RESULT ===")
                log("cbs=\(del.callbacks) samples=\(del.totalSamples) emptyBufs=\(del.emptyBuffers) noFmt=\(del.noFormatDesc) pk=\(String(format:"%.0f",pk))dBFS")
                log(del.peakAbs > 0.01 ? "ACQUIRED: Zoom app audio captured" : "NO AUDIO: samples=0 or silence")
                exit(0)
            }
            return // don't fall through to normal capture
        }

        if dumpAppsMode {
            log("=== ZOOM PID WINDOWS (all on-screen) ===")
            for w in content.windows where w.isOnScreen && w.frame.width > 0 && w.frame.height > 0 {
                log("  id=\(w.windowID) \(Int(w.frame.width))x\(Int(w.frame.height)) pid=\(w.owningApplication?.processID ?? 0) bundle=\(w.owningApplication?.bundleIdentifier ?? "?") title=\"\(String((w.title ?? "").prefix(80)))\"")
            }
            exit(0)
        }

        let sender = AudioChunkSender(backendURL: audioURL, meetingUUID: meetingUUID)
        var del: AudioDelegate? = nil

        // Start remote capture only if a REAL meeting window is found.
        // Known auxiliary Zoom windows produce callbacks but zero audio —
        // reject them explicitly.
        let knownNonMeetingTitles: Set<String> = [
            "zoom annotation entrypoint",
            "Annotation - Zoom",
            "zoom share statusbar window",
            "zoom floating video window",
            "Zoom Workplace",
        ]
        let zoomWins = content.windows.filter {
            $0.owningApplication?.bundleIdentifier == "us.zoom.xos" &&
            $0.isOnScreen && $0.frame.width > 0 && $0.frame.height > 0
        }
        log("On-screen Zoom windows: \(zoomWins.count)")
        for (i, w) in zoomWins.enumerated() {
            log("  w[\(i)] id=\(w.windowID) \(Int(w.frame.width))x\(Int(w.frame.height)) \"\(String((w.title ?? "").prefix(60)))\"")
        }
        // Candidate: not a known auxiliary window, reasonably sized
        // (meeting window is substantial, auxiliary windows are small/overlay).
        let candidates = zoomWins.filter { w in
            let title = (w.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if title.isEmpty { return false }
            if knownNonMeetingTitles.contains(title) { return false }
            // Reject overlay-sized windows (< 300x200 is a status bar / floating video)
            return w.frame.width >= 300 && w.frame.height >= 200
        }
        // Selection priority: "Zoom Meeting" in title → largest candidate
        let meetingWin = candidates.first(where: { ($0.title ?? "").contains("Zoom Meeting") })
        let largestCandidate = candidates.max(by: { ($0.frame.width * $0.frame.height) < ($1.frame.width * $1.frame.height) })
        let selectedWin = meetingWin ?? largestCandidate
        if let win = selectedWin, let display = content.displays.first {
            log("Selected Zoom meeting window: \"\(String(win.title?.prefix(60) ?? ""))\" id=\(win.windowID)")
            let d = AudioDelegate(); retainedDelegate = d
            d.sender = sender
            del = d

            let filter = SCContentFilter(display: display, including: [win])
            let cfg = SCStreamConfiguration()
            cfg.width = 2; cfg.height = 2; cfg.pixelFormat = kCVPixelFormatType_32BGRA
            cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1); cfg.showsCursor = false
            cfg.capturesAudio = true; cfg.sampleRate = 48000; cfg.channelCount = 2

            let stream = SCStream(filter: filter, configuration: cfg, delegate: d)
            retainedStream = stream
            try! stream.addStreamOutput(d, type: .audio, sampleHandlerQueue: .global())
            stream.startCapture()
            log("Remote capture started")
        } else {
            log("ERROR: No capturable Zoom meeting window found.")
            log("  Available windows were: \(zoomWins.map { "\"\($0.title ?? "")\"" }.joined(separator: ", "))")
            log("  Bring the actual meeting window to the foreground (click 'Back to meeting') and retry.")
        }

        var mic: MicCapture? = nil
        if enableMic {
            mic = MicCapture()
            mic?.sender = sender
            mic?.start()
            log("Mic: \(mic?.started == true ? "started" : "FAILED")")
        }

        // SIGTERM/SIGINT (from the ACCORD helper's STOP) end the capture
        // cleanly: stop streams, flush the partial chunk, drain the send
        // queue, then exit. SIG_IGN prevents the default terminate so the
        // dispatch source handler can run the teardown instead. The sources
        // are retained globally — a local DispatchSource is released the
        // moment this closure returns, silently cancelling the handler.
        stopFlag = StopFlag()
        retainedTermSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
        retainedIntSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .global())
        retainedTermSource?.setEventHandler { stopFlag?.value = true }
        retainedIntSource?.setEventHandler { stopFlag?.value = true }
        retainedTermSource?.resume(); retainedIntSource?.resume()
        signal(SIGTERM, SIG_IGN); signal(SIGINT, SIG_IGN)

        DispatchQueue.global().async {
            var i = 0
            while i < captureSecs && !(stopFlag?.value ?? false) {
                sleep(1)
                i += 1
                if i % 5 == 0 {
                    if let del = del {
                        let rpk = del.peakAbs > 0.000001 ? 20.0 * log10(Double(del.peakAbs)) : -100.0
                        log("  [\(String(format:"%3d",i))s] remote: cbs=\(del.callbacks) samp=\(del.totalSamples) pk=\(String(format:"%.0f",rpk))dB | \(sender.summary())")
                        if i == 15 && del.totalSamples == 0 {
                            log("  WARN: 15s elapsed with 0 audio samples — selected window may not carry meeting audio")
                        }
                    } else {
                        log("  [\(String(format:"%3d",i))s] remote disabled (no meeting window) | \(sender.summary())")
                    }
                }
            }
            retainedStream?.stopCapture()
            mic?.stop()
            sender.flush()          // send the partial tail chunk
            sender.waitUntilIdle()  // drain in-flight uploads before exit
            log("=== FINAL ===")
            if let del = del {
                log("REMOTE: cbs=\(del.callbacks) samples=\(del.totalSamples) ablFallback=\(del.ablFallback) extractFail=\(del.extractionFailures) emptyBufs=\(del.emptyBuffers) noFmt=\(del.noFormatDesc) | \(sender.summary())")
            } else {
                log("REMOTE: disabled (no Zoom window) | \(sender.summary())")
            }
            exit(0)
        }
    }
}
dispatchMain()
