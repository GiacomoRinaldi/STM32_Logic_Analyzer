import serial
import struct
import csv
import threading
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import defaultdict, deque

# ========================
# Config
# ========================
SERIAL_PORT = '/dev/tty.usbmodem385A439452311'  # Update as needed
BAUDRATE = 115200
SAMPLE_STRUCT = struct.Struct("<IB")  # uint32_t timestamp + uint8_t value
SAMPLE_SIZE = SAMPLE_STRUCT.size  # 5 bytes per sample
MAX_SAMPLES = 2500000  # Max samples per channel for plotting (2.5 mill)

# ========================
# Data Storage
# ========================
channel_data = defaultdict(lambda: deque(maxlen=MAX_SAMPLES))
prev_levels = {ch: 0 for ch in range(4)}  # previous pin values

# ========================
# User Setup Phase
# ========================

def get_comm_type():
    comm_type = input("Enter communication type (UART, SPI, I2C): ").strip().upper()
    if comm_type not in {"UART", "SPI", "I2C"}:
        print("Invalid communication type.")
        exit(1)
    return comm_type

def get_channel_mapping(comm_type):
    mapping = {}
    if comm_type == "UART":
        mapping[0] = input("Assign channel CH1 to (RX or TX): ").strip().upper()
        mapping[1] = input("Assign channel CH2 to (RX or TX): ").strip().upper()
    elif comm_type == "SPI":
        mapping[0] = input("Assign channel CH1 to (MOSI, MISO, CLK, SS): ").strip().upper()
        mapping[1] = input("Assign channel CH2 to (MOSI, MISO, CLK, SS): ").strip().upper()
        mapping[2] = input("Assign channel CH3 to (MOSI, MISO, CLK, SS): ").strip().upper()
        mapping[3] = input("Assign channel CH4 to (MOSI, MISO, CLK, SS): ").strip().upper()
    elif comm_type == "I2C":
        mapping[0] = input("Assign channel CH1 to (CLK or SDA): ").strip().upper()
        mapping[1] = input("Assign channel CH2 to (CLK or SDA): ").strip().upper()
    return mapping

# ========================
# Serial Reader Thread
# ========================
def read_usb(mapping):
    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
    with open("bitlog.csv", "w", newline='') as f:
        writer = csv.writer(f)
        
        # Create header with channel names
        header = ["Time"]
        for ch in range(4):
            if ch in mapping:
                header.append(f"{mapping[ch]}")
            else:
                header.append(f"CH{ch+1}")
        writer.writerow(header)
        
        buffer = bytearray()
        while True:
            chunk = ser.read(256)
            buffer.extend(chunk)
            
            while len(buffer) >= SAMPLE_SIZE:
                raw = buffer[:SAMPLE_SIZE]
                buffer = buffer[SAMPLE_SIZE:]
                timestamp, value = SAMPLE_STRUCT.unpack(raw)
                
                # Extract all 4 channels
                levels = [(value >> ch) & 0x1 for ch in range(4)]
                
                # Append to plot buffers
                for ch in range(4):
                    channel_data[ch].append((timestamp, levels[ch]))
                
                # Write full line to CSV
                writer.writerow([timestamp] + levels)
                f.flush()  # Ensure data is written to file immediately

# ========================
# Plot Update Function (with step-wise waveform)
# ========================
def update_plot(_):
    for ch, line in lines.items():
        if channel_data[ch]:
            raw_times, raw_levels = zip(*channel_data[ch])
            
            # Create step-wise waveform: duplicate each time, except the last
            times = []
            levels = []
            for i in range(len(raw_times)):
                times.append(raw_times[i])
                levels.append(raw_levels[i])
                if i < len(raw_times) - 1:
                    times.append(raw_times[i + 1])
                    levels.append(raw_levels[i])  # Hold current level until next edge
            
            line.set_data(times, levels)
            ax = line.axes
            
            # Dynamic x-axis scaling with much larger window
            if len(times) > 0:
                if len(times) > 1:
                    # Show a large window of recent data
                    latest_time = raw_times[-1]
                    window_size = 200000  # Much larger window size
                    
                    ax.set_xlim(latest_time - window_size, latest_time + window_size/10)
                else:
                    # Single point total
                    ax.set_xlim(times[0] - 25000, times[0] + 25000)

    return list(lines.values())

# ========================
# Main Function
# ========================
def main():
    global lines

    # User setup phase
    comm_type = get_comm_type()
    mapping = get_channel_mapping(comm_type)

    # Create one subplot per assigned channel
    num_channels = len(mapping)
    fig, axes = plt.subplots(num_channels, 1, sharex=True, figsize=(10, 2 * num_channels))
    if num_channels == 1:
        axes = [axes]  # ensure it's iterable

    lines = {}

    # Create a mapping from channel index to name for subplot labels
    channel_names = {ch: mapping[ch] for ch in mapping}

    # Setup plots for assigned channels only
    for idx, (ch, ax) in enumerate(zip(mapping, axes)):
        lines[ch], = ax.plot([], [], label=f"{channel_names[ch]}", drawstyle='steps-post')
        ax.set_ylim(-0.5, 1.5)
        ax.set_ylabel("Logic Level")
        ax.set_title(f"Channel {ch+1}: {channel_names[ch]}")
        ax.legend(loc="upper right")

    axes[-1].set_xlabel("Time (cycles)")
    plt.tight_layout()

    # Start serial reader thread
    thread = threading.Thread(target=read_usb, args=(mapping,), daemon=True)
    thread.start()

    # Start animation
    ani = animation.FuncAnimation(fig, update_plot, interval=10)
    plt.show()

if __name__ == "__main__":
    main()