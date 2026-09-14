// Native system-audio transport. No video output, files, networking or accounts.
// Build with tools/build_macos_audio.py on macOS 14+.
import Foundation
import ScreenCaptureKit
import CoreMedia
import CoreAudio
import CoreGraphics
import Darwin

private final class Transport {
    private let writer = DispatchQueue(label: "local.annie.audio.stdout")
    private let capacity = DispatchSemaphore(value: 64)
    private let lock = NSLock()
    private var dropped = 0

    private func write(_ message: [String: Any]) {
        do {
            var bytes = try JSONSerialization.data(withJSONObject: message, options: [.sortedKeys])
            bytes.append(10)
            try FileHandle.standardOutput.write(contentsOf: bytes)
        } catch { exit(2) } // Parent died or closed its pipe; never keep capturing.
    }

    func control(_ message: [String: Any]) { writer.sync { write(message) } }

    func audio(_ bytes: Data, time: Double) {
        guard capacity.wait(timeout: .now()) == .success else {
            lock.lock(); dropped += 1; lock.unlock()
            return
        }
        writer.async {
            defer { self.capacity.signal() }
            self.lock.lock(); let lost = self.dropped; self.dropped = 0; self.lock.unlock()
            if lost > 0 { self.write(["type": "gap", "count": lost]) }
            self.write(["type": "pcm", "time": time, "data": bytes.base64EncodedString()])
        }
    }
}

private final class SystemCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    private let output: Transport
    private let sampleQueue = DispatchQueue(label: "local.annie.audio.samples", qos: .userInitiated)
    private var stream: SCStream?
    private let lock = NSLock()
    private var closing = false
    private var ready = false

    init(output: Transport) { self.output = output }

    private func claimShutdown() -> Bool {
        lock.lock(); defer { lock.unlock() }
        if closing { return false }
        closing = true
        return true
    }

    func start() async throws {
        guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
            throw NSError(domain: "LectureStudio", code: 1, userInfo: [NSLocalizedDescriptionKey:
                "Allow Lecture Studio in System Settings > Privacy & Security > Screen & System Audio Recording, then restart Studio."])
        }
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        guard let display = content.displays.first else {
            throw NSError(domain: "LectureStudio", code: 2, userInfo: [NSLocalizedDescriptionKey: "No display is available for system-audio capture."])
        }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 16000
        config.channelCount = 1
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.showsCursor = false
        let capture = SCStream(filter: filter, configuration: config, delegate: self)
        // Deliberately register only .audio: no screen frames leave ScreenCaptureKit.
        try capture.addStreamOutput(self, type: .audio, sampleHandlerQueue: sampleQueue)
        stream = capture
        try await capture.startCapture()
        output.control(["type": "ready", "protocol": 1, "rate": 16000, "channels": 1, "bits": 16,
                        "clock": ProcessInfo.processInfo.systemUptime])
        lock.lock(); ready = true; lock.unlock()
    }

    func finish(error: String? = nil) {
        guard claimShutdown() else { return }
        Task {
            if let stream = self.stream { try? await stream.stopCapture() }
            // Ensure in-flight audio callbacks have enqueued their last packets.
            self.sampleQueue.sync {}
            if let error { self.output.control(["type": "error", "text": error]) }
            self.output.control(["type": "stopped"])
            exit(error == nil ? 0 : 1)
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        finish(error: "System audio stopped: \(error.localizedDescription)")
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of outputType: SCStreamOutputType) {
        lock.lock(); let active = ready && !closing; lock.unlock()
        guard active else { return }
        guard outputType == .audio, sampleBuffer.isValid,
              CMSampleBufferGetNumSamples(sampleBuffer) > 0 else { return }
        do {
            try sampleBuffer.withAudioBufferList { list, _ in
                guard let description = sampleBuffer.formatDescription?.audioStreamBasicDescription,
                      description.mFormatID == kAudioFormatLinearPCM,
                      description.mSampleRate == 16000,
                      description.mChannelsPerFrame == 1,
                      description.mBitsPerChannel == 32,
                      description.mFormatFlags & kAudioFormatFlagIsFloat != 0,
                      description.mFormatFlags & kAudioFormatFlagIsBigEndian == 0,
                      let buffer = list.first, let pointer = buffer.mData else {
                    self.finish(error: "ScreenCaptureKit returned an unsupported PCM format.")
                    return
                }
                let count = Int(buffer.mDataByteSize) / MemoryLayout<Float>.size
                guard count > 0, count <= 16000 else {
                    self.finish(error: "Invalid system-audio packet size."); return
                }
                let input = pointer.assumingMemoryBound(to: Float.self)
                var samples = [Int16](repeating: 0, count: count)
                for index in 0..<count {
                    let value = input[index].isFinite ? input[index] : 0
                    samples[index] = Int16(max(-32768, min(32767, (value * 32768).rounded()))).littleEndian
                }
                // SCK presentation timestamps use the host clock. Convert to
                // packet age so the Python side needn't assume the same epoch.
                let pts = CMTimeGetSeconds(sampleBuffer.presentationTimeStamp)
                let age = ProcessInfo.processInfo.systemUptime - pts
                let timestamp = (age.isFinite && age >= 0 && age < 5) ? pts :
                    ProcessInfo.processInfo.systemUptime - Double(count) / 16000
                samples.withUnsafeBytes { bytes in
                    self.output.audio(Data(bytes), time: timestamp)
                }
            }
        } catch {
            finish(error: "Could not read system audio: \(error.localizedDescription)")
        }
    }
}

@main
private enum LectureAudioCapture {
    @available(macOS 14.2, *)
    private static func activeAudioProcesses() -> [Int32] {
        // Read activity flags only. No taps, IOProc, streams or permission requests.
        var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyProcessObjectList,
            mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size) == noErr,
              size >= UInt32(MemoryLayout<AudioObjectID>.size), size % 4 == 0, size <= 1024 * 1024 else { return [] }
        var objects = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        let status = objects.withUnsafeMutableBytes { bytes in
            AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, bytes.baseAddress!)
        }
        guard status == noErr else { return [] }
        var result: [Int32] = []
        for object in objects {
            var running: UInt32 = 0
            var runningSize = UInt32(MemoryLayout<UInt32>.size)
            var runningAddress = AudioObjectPropertyAddress(mSelector: kAudioProcessPropertyIsRunning,
                mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
            guard AudioObjectGetPropertyData(object, &runningAddress, 0, nil, &runningSize, &running) == noErr,
                  running != 0 else { continue }
            var pid: Int32 = 0
            var pidSize = UInt32(MemoryLayout<Int32>.size)
            var pidAddress = AudioObjectPropertyAddress(mSelector: kAudioProcessPropertyPID,
                mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
            if AudioObjectGetPropertyData(object, &pidAddress, 0, nil, &pidSize, &pid) == noErr, pid > 0 {
                result.append(pid)
            }
        }
        return result
    }

    static func main() {
        signal(SIGPIPE, SIG_IGN)
        let output = Transport()
        if CommandLine.arguments == [CommandLine.arguments[0], "--audio-processes"] {
            let pids: [Int32]
            if #available(macOS 14.2, *) { pids = activeAudioProcesses() } else { pids = [] }
            output.control(["type": "audio-processes", "pids": pids])
            return
        }
        if CommandLine.arguments.contains("--self-test") {
            // Import/link/protocol check only: NEVER prompt or open capture.
            output.control(["type": "capabilities", "protocol": 1, "system_audio": true,
                            "rate": 16000, "channels": 1, "bits": 16])
            return
        }
        guard CommandLine.arguments == [CommandLine.arguments[0], "--capture"] else {
            output.control(["type": "error", "text": "Expected --capture or --self-test."])
            exit(2)
        }
        let recorder = SystemCapture(output: output)
        // EOF is as important as Stop: a killed parent must never leave recording running.
        DispatchQueue.global(qos: .utility).async {
            while let command = readLine() {
                if command == "stop" { break }
            }
            recorder.finish()
        }
        Task {
            do { try await recorder.start() }
            catch { recorder.finish(error: error.localizedDescription) }
        }
        dispatchMain()
    }
}
