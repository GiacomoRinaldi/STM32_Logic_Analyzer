import serial
import struct
import time

# === Configuration ===
PORT = '/dev/ttyACM0'      # Change to COM port (e.g., 'COM3' on Windows)
BAUDRATE = 115200          # Doesn't matter for USB CDC, but needed by pyserial
CHUNK_SIZE = 4             # 1 byte channel, 3 bytes timestamp

def decode_event(data):
    """Decode 4-byte event: 1 byte channel + 3 byte timestamp (little-endian)"""
    if len(data) != 4:
        return None
    channel = data[0]
    # Unpack 3-byte little-endian integer → pad with zero byte at the end
    timestamp = data[1] | (data[2] << 8) | (data[3] << 16)
    return channel, timestamp

def main():
    print(f"Opening serial port {PORT}...")
    ser = serial.Serial(PORT, BAUDRATE, timeout=1)

    buffer = b''
    try:
        print("Listening for events...\n")
        while True:
            buffer += ser.read(64)  # Read a USB packet

            while len(buffer) >= CHUNK_SIZE:
                event = buffer[:CHUNK_SIZE]
                buffer = buffer[CHUNK_SIZE:]

                result = decode_event(event)
                if result:
                    channel, timestamp = result
                    print(f"CH{channel} @ {timestamp} µs")
    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
