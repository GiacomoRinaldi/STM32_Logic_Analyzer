import serial
import struct
import csv
import threading
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import defaultdict, deque

# ========================
# Data Structures
# ========================

channel_data = defaultdict(lambda: deque(maxlen=1000))  # stores (time, edge)
data_log = []  # stores raw CSV log

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
# USB Handler
# ========================

def decode_usb_packet(packet_bytes):
    if len(packet_bytes) != 4:
        return None
    data, = struct.unpack('<I', packet_bytes)
    edge = (data >> 31) & 0x1
    channel = (data >> 29) & 0x3
    time = data & 0x1FFFFFFF
    return edge, channel, time

# ========================
# Real-Time Update Func
# ========================

def update_plot(frame):
    for ch, line in lines.items():
        if channel_data[ch]:
            raw_times, raw_edges = zip(*channel_data[ch])
            
            # Create step-wise waveform: duplicate each time, except the last
            times = []
            edges = []
            for i in range(len(raw_times)):
                times.append(raw_times[i])
                edges.append(raw_edges[i])
                if i < len(raw_times) - 1:
                    times.append(raw_times[i + 1])
                    edges.append(raw_edges[i])  # Hold current level until next edge
            
            line.set_data(times, edges)
            ax = line.axes
            
            # Fix the x-axis scaling issue
            if len(times) > 0:
                if len(times) > 1:
                    # Detect current byte by finding the largest time gap (>1000 units indicates new byte)
                    current_byte_start = 0
                    for i in range(len(raw_times) - 1, 0, -1):
                        if raw_times[i] - raw_times[i-1] > 1000:  # Gap indicates new byte
                            current_byte_start = i
                            break
                    
                    # Extract times for current byte only
                    current_byte_times = raw_times[current_byte_start:]
                    
                    if len(current_byte_times) > 1:
                        byte_start = min(current_byte_times)
                        byte_end = max(current_byte_times)
                        byte_center = (byte_start + byte_end) / 2
                        byte_width = byte_end - byte_start
                        
                        # Window should be slightly wider than one byte
                        window_size = max(byte_width * 1.5, 1500)
                        
                        ax.set_xlim(byte_center - window_size/2, byte_center + window_size/2)
                    else:
                        # Single edge in current byte, center on it
                        ax.set_xlim(current_byte_times[0] - 750, current_byte_times[0] + 750)
                else:
                    # Single point total
                    ax.set_xlim(times[0] - 750, times[0] + 750)

    return list(lines.values())

# ========================
# Main Function
# ========================

def main():
    global lines 

    comm_type = get_comm_type()
    mapping = get_channel_mapping(comm_type)

    # Create one subplot per channel
    num_channels = len(mapping)
    fig, axes = plt.subplots(num_channels, 1, sharex=True, figsize=(10, 2 * num_channels))
    if num_channels == 1:
        axes = [axes]  # ensure it's iterable

    lines = {}

    # Create a mapping from channel index to name for subplot labels
    channel_names = {ch: mapping[ch] for ch in mapping}

    for idx, (ch, ax) in enumerate(zip(mapping, axes)):
        lines[ch], = ax.plot([], [], label=f"{channel_names[ch]}")
        ax.set_xlim(0, 50000)
        ax.set_ylim(-0.5, 1.5)
        ax.set_ylabel("Edge")
        ax.set_title(f"Channel {ch+1}: {channel_names[ch]}")
        ax.legend(loc="upper right")

    axes[-1].set_xlabel("Time")

    ser = serial.Serial('/dev/tty.usbmodem385A439452311', 115200)  # Change to correct port if needed

    with open("bitlog.csv", "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Channel-Type", "Edge", "Time"])

        def read_serial():
            while True:
                packet = ser.read(4)
                decoded = decode_usb_packet(packet)
                if decoded:
                    edge, channel, time = decoded
                    channel_name = mapping.get(channel)
                    channel_data[channel].append((time, edge))
                    edge_label = "rising" if edge else "falling"
                    writer.writerow([channel_name, edge_label, time])
                    f.flush()  # Ensure data is written to file immediately

        thread = threading.Thread(target=read_serial, daemon=True)
        thread.start()

        ani = animation.FuncAnimation(fig, update_plot, interval=100)
        plt.show()

if __name__ == "__main__":
    main()