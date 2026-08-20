// 실시간 녹음 오디오를 STT Provider 계약(mono PCM16, 24kHz, 200ms Chunk)에 맞게
// 변환하는 순수 함수만 모은다. DOM/Web Audio API에 의존하지 않는다.
// `workmate-ui/lib/audio-pcm16.ts`에서 그대로 이식(19번 문서 6단계) — 수정 없이
// 옮길 수 있는 순수 모듈이다.

export const STT_SAMPLE_RATE = 24000;
export const STT_CHUNK_MS = 200;
export const STT_CHUNK_SAMPLES = (STT_SAMPLE_RATE * STT_CHUNK_MS) / 1000; // 4800 samples

/**
 * 브라우저 AudioContext의 원본 샘플레이트(보통 44100·48000Hz)를 24kHz로
 * 선형 보간 리샘플링한다.
 */
export function resampleLinear(input: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate) return input;
  const ratio = inputRate / outputRate;
  const outputLength = Math.floor(input.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i++) {
    const srcIndex = i * ratio;
    const lower = Math.floor(srcIndex);
    const upper = Math.min(lower + 1, input.length - 1);
    const frac = srcIndex - lower;
    output[i] = input[lower] * (1 - frac) + input[upper] * frac;
  }
  return output;
}

/** Web Audio의 -1..1 Float32 샘플을 16bit PCM(Little Endian)으로 변환한다. */
export function float32ToPcm16(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const clamped = Math.max(-1, Math.min(1, input[i]));
    output[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return output;
}

/** `Int16Array`를 base64 문자열로 인코딩한다(WebSocket JSON 페이로드용). */
export function pcm16ToBase64(samples: Int16Array): string {
  const bytes = new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/**
 * 임의 길이로 들어오는 오디오 블록을 정확히 200ms(4800 sample) 단위로
 * 잘라내는 누적 버퍼.
 */
export class Pcm16ChunkBuffer {
  private pending: Int16Array = new Int16Array(0);

  push(samples: Int16Array): Int16Array[] {
    const merged = new Int16Array(this.pending.length + samples.length);
    merged.set(this.pending, 0);
    merged.set(samples, this.pending.length);

    const chunks: Int16Array[] = [];
    let offset = 0;
    while (merged.length - offset >= STT_CHUNK_SAMPLES) {
      chunks.push(merged.slice(offset, offset + STT_CHUNK_SAMPLES));
      offset += STT_CHUNK_SAMPLES;
    }
    this.pending = merged.slice(offset);
    return chunks;
  }

  flush(): Int16Array | null {
    if (!this.pending.length) return null;
    const remainder = this.pending;
    this.pending = new Int16Array(0);
    return remainder;
  }
}
