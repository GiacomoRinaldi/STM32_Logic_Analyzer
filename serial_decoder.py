import serial
import struct
import csv
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import defaultdict, deque

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
# Data Structures
# ========================

channel_data = defaultdict(lambda: deque(maxlen=1000))  # stores (time, edge)
data_log = []  # stores raw CSV log

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
# Plotting
# ========================

fig, ax = plt.subplots()
lines = {}

# Set up initial empty lines for each channel (up to 4)
for ch in range(4):
    lines[ch], = ax.plot([], [], label=f"CH{ch+1}")

ax.set_xlim(0, 50000)
ax.set_ylim(-0.5, 1.5)
ax.set_xlabel("Time")
ax.set_ylabel("Edge")
ax.legend()

# ========================
# Real-Time Update Func
# ========================

def update_plot(frame):
    for ch, line in lines.items():
        if ch in channel_data:
            times, edges = zip(*channel_data[ch]) if channel_data[ch] else ([], [])
            line.set_data(times, edges)
    return lines.values()

# ========================
# Main Function
# ========================

def main():
    comm_type = get_comm_type()
    mapping = get_channel_mapping(comm_type)

    ser = serial.Serial('/dev/ttyUSB0', 115200)  # Change to correct port if needed

    with open("bitlog.csv", "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Channel-Type", "Edge", "Time"])

        def read_serial():
            while True:
                packet = ser.read(4)
                decoded = decode_usb_packet(packet)
                if decoded:
                    edge, channel, time = decoded
                    channel_name = mapping.get(channel+1)
                    channel_data[channel].append((time, edge))
                    edge_label = "rising" if edge else "falling"
                    writer.writerow([channel_name, edge_label, time])

        import threading
        thread = threading.Thread(target=read_serial, daemon=True)
        thread.start()

        ani = animation.FuncAnimation(fig, update_plot, interval=100)
        plt.show()

if __name__ == "__main__":
    main()