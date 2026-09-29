import AVFoundation
import Foundation

struct Note: Decodable {
    let string: Int
    let pitch: UInt8
    let start_seconds: Double
    let end_seconds: Double
}
struct Lesson: Decodable {
    let duration_seconds: Double
    let notes: [Note]
}
struct Event {
    let frame: Int64
    let string: Int
    let pitch: UInt8
    let on: Bool
}

let lesson = try JSONDecoder().decode(Lesson.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
let rate = 44100.0
let engine = AVAudioEngine()
let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2)!
let bank = URL(fileURLWithPath: "/System/Library/Components/CoreAudio.component/Contents/Resources/gs_instruments.dls")
var samplers: [AVAudioUnitSampler] = []
for _ in 1...6 {
    let sampler = AVAudioUnitSampler()
    engine.attach(sampler)
    engine.connect(sampler, to: engine.mainMixerNode, format: format)
    try sampler.loadSoundBankInstrument(at: bank, program: 24, bankMSB: UInt8(kAUSampler_DefaultMelodicBankMSB), bankLSB: 0)
    samplers.append(sampler)
}
engine.mainMixerNode.outputVolume = 0.45
try engine.enableManualRenderingMode(.offline, format: format, maximumFrameCount: 4096)
try engine.start()
let settings: [String: Any] = [AVFormatIDKey: kAudioFormatLinearPCM,
    AVSampleRateKey: rate, AVNumberOfChannelsKey: 2, AVLinearPCMBitDepthKey: 16,
    AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false]
var file: AVAudioFile? = try AVAudioFile(forWriting: URL(fileURLWithPath: CommandLine.arguments[2]), settings: settings)
let buffer = AVAudioPCMBuffer(pcmFormat: engine.manualRenderingFormat, frameCapacity: 4096)!
var events: [Event] = []
for note in lesson.notes {
    events.append(Event(frame: Int64((note.start_seconds * rate).rounded()), string: note.string, pitch: note.pitch, on: true))
    events.append(Event(frame: Int64((note.end_seconds * rate).rounded()), string: note.string, pitch: note.pitch, on: false))
}
events.sort { a, b in a.frame == b.frame ? (!a.on && b.on) : a.frame < b.frame }
let end = Int64((lesson.duration_seconds * rate).rounded())
var current: Int64 = 0
var index = 0
var retries = 0
while current < end {
    while index < events.count && events[index].frame <= current {
        let e = events[index]
        if e.on { samplers[e.string-1].startNote(e.pitch, withVelocity: 85, onChannel: 0) }
        else { samplers[e.string-1].stopNote(e.pitch, onChannel: 0) }
        index += 1
    }
    let boundary = index < events.count ? min(end, events[index].frame) : end
    let count = AVAudioFrameCount(min(4096, boundary-current))
    let status = try engine.renderOffline(count, to: buffer)
    if status == .success {
        try file!.write(from: buffer)
        current += Int64(buffer.frameLength)
        retries = 0
    } else {
        retries += 1
        if retries > 100 { fatalError("Offline rendering stalled: \(status)") }
    }
}
engine.stop()
file = nil
print("WAV: \(CommandLine.arguments[2]) (\(lesson.duration_seconds) seconds)")
