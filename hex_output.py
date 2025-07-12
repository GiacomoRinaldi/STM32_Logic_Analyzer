import csv
import sys
from collections import defaultdict

# ========== UART DECODER ==========
def decode_uart(filepath):
    import csv

    baud_rate = int(input("Enter UART baud rate (e.g., 9600): "))
    bit_time_us = 1_000_000 / baud_rate

    # Parse the CSV and collect edges for each channel
    channel_data = {}
    with open(filepath, newline='') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) != 3:
                continue
            channel, edge, timestamp = row
            if channel not in channel_data:
                channel_data[channel] = []
            channel_data[channel].append((edge, int(timestamp)))

    # Decode each channel separately
    for channel, transitions in channel_data.items():
        transitions.sort(key=lambda x: x[1])  # Sort by time
        bits = []
        decoded_bytes = []

        i = 0
        while i < len(transitions) - 1:
            edge, time = transitions[i]
            next_edge, next_time = transitions[i + 1]

            # Detect start bit: falling edge
            if edge == "falling":
                start_time = time + int(bit_time_us * 1.5)  # center of first data bit
                byte = 0
                for bit_index in range(8):
                    sample_time = start_time + int(bit_index * bit_time_us)
                    # Find nearest transition before or after sample_time
                    sampled_state = 1  # default high if idle
                    for j in range(i, len(transitions)):
                        if transitions[j][1] > sample_time:
                            if transitions[j][0] == "rising":
                                sampled_state = 1
                            else:
                                sampled_state = 0
                            break
                    byte |= (sampled_state << bit_index)
                decoded_bytes.append(byte)
                i += 10  # skip past full frame (start, 8 data, stop)
            else:
                i += 1

        output_file = f"{channel}_decoded_uart.txt"
        with open(output_file, "w") as f:
            for b in decoded_bytes:
                f.write(f"{b:02X} ")
        print(f"Decoded UART data for channel {channel} written to {output_file}")

# ========== SPI DECODER ==========
def decode_spi(csv_file):
    transitions = defaultdict(list)
    output_lines = []

    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            channel, edge, timestamp = row
            transitions[channel].append((edge, float(timestamp)))

    clk_edges = [t for e, t in transitions['SCK'] if e == 'RISING']
    mosi_values = transitions['MOSI']
    miso_values = transitions['MISO']

    mosi_byte = 0
    miso_byte = 0
    bit_count = 0

    for clk_time in clk_edges:
        # Find nearest value for MOSI and MISO before clock edge
        mosi_level = 0
        for e, t in reversed(mosi_values):
            if t <= clk_time:
                mosi_level = 1 if e == 'RISING' else 0
                break

        miso_level = 0
        for e, t in reversed(miso_values):
            if t <= clk_time:
                miso_level = 1 if e == 'RISING' else 0
                break

        mosi_byte = (mosi_byte << 1) | mosi_level
        miso_byte = (miso_byte << 1) | miso_level
        bit_count += 1

        if bit_count == 8:
            output_lines.append(f"{clk_time:.6f}s: SPI MOSI = 0x{mosi_byte:02X}, MISO = 0x{miso_byte:02X}")
            mosi_byte = 0
            miso_byte = 0
            bit_count = 0

    with open("decoded_spi_output.txt", "w") as f:
        for line in output_lines:
            f.write(line + "\n")
    print("Decoded SPI output written to 'decoded_spi_output.txt'")


# ========== I2C DECODER ==========
def decode_i2c(csv_file):
    transitions = defaultdict(list)
    output_lines = []

    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            channel, edge, timestamp = row
            transitions[channel].append((edge, float(timestamp)))

    sda = transitions['SDA']
    scl = transitions['SCL']

    bits = []
    byte = 0
    bit_count = 0

    for edge, t in scl:
        if edge != 'RISING':
            continue

        # Sample SDA at SCL rising edge
        sda_val = 0
        for e, st in reversed(sda):
            if st <= t:
                sda_val = 1 if e == 'RISING' else 0
                break

        bits.append(sda_val)
        bit_count += 1

        if bit_count == 8:
            byte = sum([bit << (7 - i) for i, bit in enumerate(bits)])
            output_lines.append(f"{t:.6f}s: I2C byte = 0x{byte:02X}")
            bits = []
            bit_count = 0

    with open("decoded_i2c_output.txt", "w") as f:
        for line in output_lines:
            f.write(line + "\n")
    print("Decoded I2C output written to 'decoded_i2c_output.txt'")


# ========== MAIN SELECTOR ==========
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python hex_output.py <protocol> <csv_file>")
        sys.exit(1)

    protocol = sys.argv[1].lower()
    file_path = sys.argv[2]

    if protocol == 'uart':
        decode_uart(file_path)
    elif protocol == 'spi':
        decode_spi(file_path)
    elif protocol == 'i2c':
        decode_i2c(file_path)
    else:
        print("Unsupported protocol. Use 'uart', 'spi', or 'i2c'.")