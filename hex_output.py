import csv
import sys
from collections import defaultdict

def get_line_level_at(transitions, sample_time):
    level = 1  # UART idle line is high
    for edge, t in transitions:
        if t > sample_time:
            break
        if edge == 'falling':
            level = 0
        elif edge == 'rising':
            level = 1
    return level

# ========== UART DECODER ==========
def decode_uart(filepath, baud_rate, data_bits=8, parity='N', stop_bits=1):
    bit_time_us = 1_000_000 / baud_rate
    print(f"Decoding UART: {baud_rate} baud, {data_bits} data bits, parity {parity}, {stop_bits} stop bits")

    # Read CSV and collect transitions per channel
    channel_data = {}
    with open(filepath, newline='') as csvfile:
        reader = csv.reader(csvfile)
        next(reader)  # skip header
        for row in reader:
            if len(row) != 3:
                continue
            channel, edge, timestamp = row
            if channel not in channel_data:
                channel_data[channel] = []
            channel_data[channel].append((edge.lower(), int(timestamp)))

    for channel, transitions in channel_data.items():
        transitions.sort(key=lambda x: x[1])  # sort by timestamp
        decoded_bytes = []
        i = 0
        while i < len(transitions) - 1:
            edge, time = transitions[i]
            # Detect start bit: falling edge
            if edge == 'falling':
                print(f"Found start bit on channel {channel} at time {time}")
                start_time = time + int(bit_time_us * 1.5)  # center of first data bit

                bits = []
                for bit_index in range(data_bits):
                    sample_time = start_time + int(bit_time_us * bit_index)
                    sampled_state = get_line_level_at(transitions, sample_time)
                    bits.append(sampled_state)

                # Parity bit sample (if any)
                parity_bit = None
                if parity.upper() in ('E', 'O'):
                    parity_sample_time = start_time + int(bit_time_us * data_bits)
                    parity_bit = get_line_level_at(transitions, parity_sample_time)

                # Compose byte (LSB first)
                byte = 0
                for idx, bit_val in enumerate(bits):
                    byte |= (bit_val << idx)

                # Check parity if enabled
                if parity.upper() == 'E':  # even parity
                    expected_parity = (sum(bits) % 2 == 0)
                    if parity_bit != expected_parity:
                        print(f"Warning: parity error on byte {byte:02X}")
                elif parity.upper() == 'O':  # odd parity
                    expected_parity = (sum(bits) % 2 == 1)
                    if parity_bit != expected_parity:
                        print(f"Warning: parity error on byte {byte:02X}")

                decoded_bytes.append(byte)

                # Skip whole frame: start + data + parity + stop bits
                frame_bits = 1 + data_bits + (1 if parity_bit is not None else 0) + stop_bits
                i += frame_bits
            else:
                i += 1

        # Output decoded bytes as hex and ASCII
        print(f"Decoded UART data for channel {channel}:")
        print("Hex: ", " ".join(f"{b:02X}" for b in decoded_bytes))
        print("ASCII:", "".join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes))

        output_file = f"{channel}_decoded_uart.txt"
        with open(output_file, "w") as f:
            f.write(" ".join(f"{b:02X}" for b in decoded_bytes) + "\n")
            f.write("".join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes))
        print(f"Decoded UART data written to {output_file}")

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
        baud = int(input("Enter UART baud rate (e.g., 9600): "))
        data_bits = int(input("Enter number of data bits (7 or 8): "))
        parity = input("Enter parity (N = none, E = even, O = odd): ").upper()
        stop_bits = int(input("Enter number of stop bits (1 or 2): "))
        decode_uart(file_path, baud, data_bits, parity, stop_bits)
    elif protocol == 'spi':
        decode_spi(file_path)
    elif protocol == 'i2c':
        decode_i2c(file_path)
    else:
        print("Unsupported protocol. Use 'uart', 'spi', or 'i2c'.")