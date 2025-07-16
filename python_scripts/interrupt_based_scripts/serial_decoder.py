import csv
import sys
from collections import defaultdict

# ========== UART DECODER ==========
def get_line_level_at(transitions, sample_time):
    """Get the logic level at a specific time based on transitions"""
    level = 1  # UART idle line is high
    for edge, t in transitions:
        if t > sample_time:
            break
        if edge == 'falling':
            level = 0
        elif edge == 'rising':
            level = 1
    return level

def detect_uart_frames(transitions, bit_time_us):
    """
    Improved UART frame detection that handles inter-character gaps properly
    """
    frames = []
    min_start_width = bit_time_us * 0.5  # Start bit must be at least 50% of bit time
    min_idle_time = bit_time_us * 0.8    # Minimum idle time between frames
    
    i = 0
    while i < len(transitions):
        edge, time = transitions[i]
        
        # Look for falling edge (potential start bit)
        if edge != 'falling':
            i += 1
            continue
            
        # Check if line was idle (high) for sufficient time before this falling edge
        if i > 0:
            prev_edge, prev_time = transitions[i-1]
            if prev_edge == 'falling' and (time - prev_time) < min_idle_time:
                i += 1
                continue
        
        # Find the next rising edge to measure start bit width
        start_bit_end = None
        for j in range(i + 1, len(transitions)):
            next_edge, next_time = transitions[j]
            if next_edge == 'rising':
                start_bit_width = next_time - time
                if start_bit_width >= min_start_width:
                    start_bit_end = next_time
                    frames.append(time)
                break
        
        i += 1
    
    return frames

def decode_uart_frame(transitions, start_time, bit_time_us, data_bits=8, parity='N'):
    """
    Decode a single UART frame starting at start_time
    """
    
    # Sample data bits at the center of each bit period
    bits = []
    for bit_index in range(data_bits):
        sample_time = start_time + int(bit_time_us * (1.5 + bit_index))
        bit_value = get_line_level_at(transitions, sample_time)
        bits.append(bit_value)
    
    # Handle parity bit if enabled
    parity_bit = None
    parity_ok = True
    if parity.upper() in ('E', 'O'):
        parity_sample_time = start_time + int(bit_time_us * (1.5 + data_bits))
        parity_bit = get_line_level_at(transitions, parity_sample_time)
        
        # Check parity
        data_ones = sum(bits)
        if parity.upper() == 'E':  
            parity_ok = (data_ones % 2) == (1 - parity_bit)
        else:  
            parity_ok = (data_ones % 2) == parity_bit
            
        if not parity_ok:
            print(f"  WARNING: Parity error!")
    
    # Check stop bit(s)
    stop_sample_time = start_time + int(bit_time_us * (1.5 + data_bits + (1 if parity != 'N' else 0)))
    stop_bit = get_line_level_at(transitions, stop_sample_time)
    if stop_bit != 1:
        print(f"  WARNING: Stop bit error! Expected 1, got {stop_bit}")
    
    # Compose byte (LSB first for UART)
    byte_value = 0
    for idx, bit_val in enumerate(bits):
        byte_value |= (bit_val << idx)
        
    return byte_value, parity_ok

def decode_uart(filepath, baud_rate, data_bits=8, parity='N', stop_bits=1):
    """
    Main UART decoder function
    """
    bit_time_us = 5_140_000 / baud_rate # set as needed based on resolution (5.14 MHz)
    
    # Read CSV file
    channel_data = {}
    try:
        with open(filepath, 'r', newline='') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader)
            print(f"CSV header: {header}")
            
            for row in reader:
                if len(row) != 3:
                    continue
                channel, edge, timestamp = row
                try:
                    timestamp = int(timestamp)
                except ValueError:
                    print(f"Warning: Invalid timestamp '{timestamp}' - skipping")
                    continue
                
                if channel not in channel_data:
                    channel_data[channel] = []
                channel_data[channel].append((edge.lower(), timestamp))
                
    except FileNotFoundError:
        print(f"Error: File '{filepath}' not found")
        return
    except Exception as e:
        print(f"Error reading file: {e}")
        return
    
    # Process each channel
    for channel, transitions in channel_data.items():
        
        # Sort transitions by time
        transitions.sort(key=lambda x: x[1])
        
        # Detect UART frames
        frame_start_times = detect_uart_frames(transitions, bit_time_us)
        
        if not frame_start_times:
            print("No valid UART frames detected!")
            continue
        
        # Decode each frame
        decoded_bytes = []
        for start_time in frame_start_times:
            try:
                byte_val, parity_ok = decode_uart_frame(transitions, start_time, bit_time_us, data_bits, parity)
                decoded_bytes.append(byte_val)
            except Exception as e:
                print(f"Error decoding frame at {start_time}µs: {e}")
        
        # Output results
        print(f"\n{'='*20} Results for {channel} {'='*20}")
        print(f"Decoded {len(decoded_bytes)} bytes:")
        print(f"Hex:   {' '.join(f'{b:02X}' for b in decoded_bytes)}")
        print(f"ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes)}")
        
        # Save to file
        output_file = f"{channel}_uart_decoded.txt"
        try:
            with open(output_file, 'w') as f:
                f.write(f"UART Decode Results - Channel {channel}\n")
                f.write(f"Baud: {baud_rate}, Data: {data_bits}, Parity: {parity}, Stop: {stop_bits}\n")
                f.write(f"Bit time: {bit_time_us:.2f}µs\n")
                f.write("=" * 50 + "\n")
                f.write(f"Hex:   {' '.join(f'{b:02X}' for b in decoded_bytes)}\n")
                f.write(f"ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes)}\n")
            print(f"Results saved to: {output_file}")
        except Exception as e:
            print(f"Error saving file: {e}")

# ========== SPI DECODER ==========
def decode_spi(csv_file, clock_polarity=0, clock_phase=0):
    """
    Decode SPI protocol
    clock_polarity: 0 = idle low, 1 = idle high
    clock_phase: 0 = sample on leading edge, 1 = sample on trailing edge
    """
    transitions = defaultdict(list)
    output_lines = []

    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            if len(row) != 3:
                continue
            channel, edge, timestamp = row
            try:
                timestamp = int(timestamp)
            except ValueError:
                continue
            transitions[channel].append((edge.lower(), timestamp))

    # Sort all transitions by time
    for channel in transitions:
        transitions[channel].sort(key=lambda x: x[1])

    # Determine sampling edge based on polarity and phase
    if clock_polarity == 0:  
        sample_edge = 'rising' if clock_phase == 0 else 'falling'
    else:  
        sample_edge = 'falling' if clock_phase == 0 else 'rising'

    clk_edges = [t for e, t in transitions.get('SCK', []) if e == sample_edge]
    mosi_transitions = transitions.get('MOSI', [])
    miso_transitions = transitions.get('MISO', [])

    print(f"Found {len(clk_edges)} clock edges for sampling")

    mosi_byte = 0
    miso_byte = 0
    bit_count = 0

    for clk_time in clk_edges:
        # Find MOSI level at clock edge
        mosi_level = 0
        for e, t in reversed(mosi_transitions):
            if t <= clk_time:
                mosi_level = 1 if e == 'rising' else 0
                break

        # Find MISO level at clock edge
        miso_level = 0
        for e, t in reversed(miso_transitions):
            if t <= clk_time:
                miso_level = 1 if e == 'rising' else 0
                break

        # SPI is MSB first
        mosi_byte = (mosi_byte << 1) | mosi_level
        miso_byte = (miso_byte << 1) | miso_level
        bit_count += 1

        if bit_count == 8:
            # Convert to ASCII characters if printable
            mosi_char = chr(mosi_byte) if 32 <= mosi_byte < 127 else '.'
            miso_char = chr(miso_byte) if 32 <= miso_byte < 127 else '.'
            
            output_lines.append(f"{clk_time}µs: SPI MOSI = 0x{mosi_byte:02X} ('{mosi_char}'), MISO = 0x{miso_byte:02X} ('{miso_char}')")
            print(f"SPI byte at {clk_time}µs: MOSI=0x{mosi_byte:02X} ('{mosi_char}'), MISO=0x{miso_byte:02X} ('{miso_char}')")
            mosi_byte = 0
            miso_byte = 0
            bit_count = 0

    # Collect all MOSI and MISO bytes for ASCII representation
    mosi_bytes = []
    miso_bytes = []
    for line in output_lines:
        # Extract hex values from output lines
        if 'MOSI = 0x' in line:
            mosi_hex = line.split('MOSI = 0x')[1].split(' ')[0]
            miso_hex = line.split('MISO = 0x')[1].split(' ')[0]
            mosi_bytes.append(int(mosi_hex, 16))
            miso_bytes.append(int(miso_hex, 16))

    with open("decoded_spi_output.txt", "w") as f:
        f.write("=== SPI Decoded Data ===\n")
        for line in output_lines:
            f.write(line + "\n")
        f.write(f"\n=== ASCII Summary ===\n")
        f.write(f"MOSI Hex: {' '.join(f'{b:02X}' for b in mosi_bytes)}\n")
        f.write(f"MOSI ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in mosi_bytes)}\n")
        f.write(f"MISO Hex: {' '.join(f'{b:02X}' for b in miso_bytes)}\n")
        f.write(f"MISO ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in miso_bytes)}\n")
    
    print(f"\nSPI ASCII Summary:")
    print(f"MOSI: {''.join(chr(b) if 32 <= b < 127 else '.' for b in mosi_bytes)}")
    print(f"MISO: {''.join(chr(b) if 32 <= b < 127 else '.' for b in miso_bytes)}")
    print(f"Decoded SPI output written to 'decoded_spi_output.txt'")

# ========== I2C DECODER ==========
def decode_i2c(csv_file):
    transitions = defaultdict(list)
    output_lines = []

    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            if len(row) != 3:
                continue
            channel, edge, timestamp = row
            try:
                timestamp = int(timestamp)
            except ValueError:
                continue
            transitions[channel].append((edge.lower(), timestamp))

    # Sort transitions by time
    for channel in transitions:
        transitions[channel].sort(key=lambda x: x[1])

    sda_transitions = transitions.get('SDA', [])
    scl_transitions = transitions.get('SCL', [])

    print(f"Found {len(sda_transitions)} SDA transitions, {len(scl_transitions)} SCL transitions")

    # Detect start/stop conditions
    start_stops = []
    scl_high_periods = []
    
    # Find SCL high periods
    scl_level = 0
    scl_high_start = None
    for edge, time in scl_transitions:
        if edge == 'rising':
            scl_level = 1
            scl_high_start = time
        elif edge == 'falling' and scl_level == 1:
            scl_level = 0
            if scl_high_start is not None:
                scl_high_periods.append((scl_high_start, time))

    # Detect start/stop conditions (SDA transitions while SCL is high)
    for sda_edge, sda_time in sda_transitions:
        for scl_start, scl_end in scl_high_periods:
            if scl_start <= sda_time <= scl_end:
                if sda_edge == 'falling':
                    start_stops.append(('START', sda_time))
                elif sda_edge == 'rising':
                    start_stops.append(('STOP', sda_time))
                break

    # Sample data bits on SCL rising edges
    bits = []
    current_byte = 0
    bit_count = 0
    decoded_bytes = []

    for edge, time in scl_transitions:
        if edge == 'rising':
            # Sample SDA at SCL rising edge
            sda_val = 0
            for e, st in reversed(sda_transitions):
                if st <= time:
                    sda_val = 1 if e == 'rising' else 0
                    break

            bits.append(sda_val)
            bit_count += 1

            if bit_count == 8:
                current_byte = sum([bit << (7 - i) for i, bit in enumerate(bits)])
                decoded_bytes.append(current_byte)
                
                # Convert to ASCII character if printable
                char_repr = chr(current_byte) if 32 <= current_byte < 127 else '.'
                output_lines.append(f"{time}µs: I2C byte = 0x{current_byte:02X} ('{char_repr}')")
                print(f"I2C byte at {time}µs: 0x{current_byte:02X} ('{char_repr}')")
                bits = []
                bit_count = 0

    # Add start/stop conditions to output
    for condition, time in start_stops:
        output_lines.append(f"{time}µs: I2C {condition}")
        print(f"I2C {condition} at {time}µs")

    # Sort output by time
    output_lines.sort(key=lambda x: int(x.split('µs:')[0]))

    with open("decoded_i2c_output.txt", "w") as f:
        f.write("=== I2C Decoded Data ===\n")
        for line in output_lines:
            f.write(line + "\n")
        f.write(f"\n=== ASCII Summary ===\n")
        f.write(f"Hex: {' '.join(f'{b:02X}' for b in decoded_bytes)}\n")
        f.write(f"ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes)}\n")
    
    print(f"\nI2C ASCII Summary:")
    print(f"Decoded bytes: {' '.join(f'{b:02X}' for b in decoded_bytes)}")
    print(f"ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes)}")
    print(f"Decoded I2C output written to 'decoded_i2c_output.txt'")

# ========== MAIN SELECTOR ==========
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python protocol_decoder.py <protocol> <csv_file>")
        print("Supported protocols: uart, spi, i2c")
        sys.exit(1)

    protocol = sys.argv[1].lower()
    file_path = sys.argv[2]

    try:
        if protocol == 'uart':
            print("UART Decoder Configuration:")
            baud = int(input("Enter UART baud rate (e.g., 9600): "))
            data_bits = int(input("Enter number of data bits (7 or 8): "))
            parity = input("Enter parity (N = none, E = even, O = odd): ").upper()
            stop_bits = int(input("Enter number of stop bits (1 or 2): "))
            decode_uart(file_path, baud, data_bits, parity, stop_bits)
            
        elif protocol == 'spi':
            print("SPI Decoder Configuration:")
            clock_pol = int(input("Enter clock polarity (0 = idle low, 1 = idle high): "))
            clock_phase = int(input("Enter clock phase (0 = sample on leading edge, 1 = trailing edge): "))
            decode_spi(file_path, clock_pol, clock_phase)
            
        elif protocol == 'i2c':
            decode_i2c(file_path)
            
        else:
            print("Unsupported protocol. Use 'uart', 'spi', or 'i2c'.")
            
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"Error: {e}")