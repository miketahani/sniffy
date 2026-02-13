/** Web Serial client for the ESP32-C6 WiFi sniffer firmware. */
import { Frame } from "./frame.js";
export declare const FILTER_ALL = 0;
export declare const FILTER_MGMT = 1;
export declare const FILTER_CTRL = 2;
export declare const FILTER_DATA = 4;
export declare class SnifferError extends Error {
    readonly cmd: number;
    readonly code: number;
    constructor(cmd: number, code: number);
}
export interface SnifferClientOptions {
    baudRate?: number;
    onFrame?: (frame: Frame) => void;
    onDisconnect?: () => void;
    /** USB vendor/product filter for requestPort(). */
    filters?: SerialPortFilter[];
}
export declare class SnifferClient {
    static readonly TIMEOUT = 3000;
    frameCount: number;
    dropped: number;
    private _port;
    private _reader;
    private _writer;
    private _running;
    private _buf;
    private _seqExpect;
    private _firstSeq;
    private _onFrame;
    private _onDisconnect;
    private _baudRate;
    private _filters;
    private _respResolve;
    constructor(options?: SnifferClientOptions);
    /** Whether the client is currently connected to a serial port. */
    get connected(): boolean;
    /**
     * Request a serial port from the user and open it.
     * Must be called from a user gesture (click, keypress, etc.).
     */
    connect(existingPort?: SerialPort): Promise<void>;
    scan(channel?: number, frameFilter?: number): Promise<void>;
    stop(): Promise<void>;
    promiscOn(): Promise<void>;
    promiscOff(): Promise<void>;
    promiscStatus(): Promise<boolean>;
    disconnect(): Promise<void>;
    private _sendCmd;
    private _readLoop;
    private _appendBuf;
    private _process;
    private _handleFrame;
}
//# sourceMappingURL=client.d.ts.map