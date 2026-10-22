declare module 'gif-encoder-2' {
  export interface ByteArray {
    data: number[];
    getData(): Buffer;
    writeByte(val: number): void;
    writeUTFBytes(str: string): void;
    writeBytes(array: number[] | Uint8Array, offset?: number, length?: number): void;
  }

  export default class GIFEncoder {
    constructor(
      width: number,
      height: number,
      algorithm?: 'neuquant' | 'octree' | string,
      useOptimizer?: boolean,
      totalFrames?: number
    );

    width: number;
    height: number;
    algorithm: string;
    useOptimizer: boolean;
    totalFrames: number;
    out: ByteArray;

    start(): void;
    finish(): void;
    addFrame(ctxOrBuffer: Buffer | Uint8Array | any): void;
    setRepeat(repeat: number): void;
    setDelay(ms: number): void;
    setQuality(quality: number): void;
    setFrameRate(fps: number): void;
    setDispose(code: number): void;
    setTransparent(color: number | string | null): void;
    setThreshold(threshold: number): void;
    setPaletteSize(size: number): void;
    createReadStream(): any;
  }
}
