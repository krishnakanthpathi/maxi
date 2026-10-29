import Foundation

/// A playback activity indicator for TTS events modeled on natural human speech
/// cadences (syllabic envelopes, vowel/consonant formant weighting, and breathing pauses).
enum SpeechWaveform {
    static func levels(at time: TimeInterval) -> [CGFloat] {
        // Syllabic envelope (~3.6 syllables/second)
        let syllable = 0.45 + 0.40 * sin(time * 3.6 * 2.0 * .pi)
        // Clause breath / phrasing cadence (~0.7 Hz)
        let clause = 0.65 + 0.35 * sin(time * 0.7 * 2.0 * .pi)
        // Combined conversational energy envelope
        let envelope = max(0.18, syllable * clause)

        // Vocal tract formant weighting (vowel body in centers, consonants in edges)
        let formantWeights: [Double] = [0.70, 0.95, 0.90, 0.65, 0.50]

        return (0..<5).map { band in
            let phase = time * (8.0 + Double(band) * 1.5) + Double(band) * 0.8
            let wave = 0.5 + 0.5 * sin(phase)
            let raw = 0.20 + 0.78 * (envelope * formantWeights[band] * (0.6 + 0.4 * wave))
            return CGFloat(max(0.20, min(0.98, raw)))
        }
    }
}
