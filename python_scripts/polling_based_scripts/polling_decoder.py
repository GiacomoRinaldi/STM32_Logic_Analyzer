import csv
import sys
from collections import defaultdict
import numpy as np

# CPU frequency for STM32F103 (72 MHz)
CPU_FREQ_HZ = 72_000_000

def cycles_to_microseconds(cycles):
    """Convert CPU cycles to microseconds"""
    return cycles / CPU_FREQ_HZ * 1_000_000

def load_csv_data(filepath):
    """Load CSV data and return channel data with cycle timestamps"""
    channel_data = {}
    
    try:
        with open(filepath, 'r', newline='') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader)
            print(f"CSV header: {header}")
            
            # Parse header to find channel columns
            time_col = 0  # First column is time
            channel_cols = {}
            for i, col_name in enumerate(header[1:], 1):  # Skip time column
                channel_cols[col_name] = i
                channel_data[col_name] = []
            
            # Read data
            for row in reader:
                if len(row) != len(header):
                    continue
                    
                try:
                    timestamp = int(row[time_col])
                except ValueError:
                    continue
                
                # Store (timestamp, level) for each channel
                for channel_name, col_idx in channel_cols.items():
                    try:
                        level = int(row[col_idx])
                        channel_data[channel_name].append((timestamp, level))
                    except (ValueError, IndexError):
                        continue
                        
    except FileNotFoundError:
        print(f"Error: File '{filepath}' not found")
        return None
    except Exception as e:
        print(f"Error reading file: {e}")
        return None
    
    return channel_data

def calculate_actual_sampling_rate(channel_data):
    """Calculate actual sampling rate from timestamp differences"""
    # Use the first channel to analyze timing
    first_channel = next(iter(channel_data.values()))
    
    if len(first_channel) < 100:
        print("Warning: Not enough samples to accurately determine sampling rate")
        return None
    
    # Calculate time differences between consecutive samples
    time_diffs = []
    for i in range(1, min(1000, len(first_channel))):  # Use first 1000 samples
        time_diff = first_channel[i][0] - first_channel[i-1][0]
        if time_diff > 0:  # Only positive differences
            time_diffs.append(time_diff)
    
    if not time_diffs:
        return None
    
    # Calculate statistics
    avg_cycles_per_sample = np.mean(time_diffs)
    std_cycles_per_sample = np.std(time_diffs)
    
    # Assuming 72 MHz CPU frequency
    CPU_FREQ_HZ = 72_000_000
    actual_sampling_rate = CPU_FREQ_HZ / avg_cycles_per_sample
    
    print(f"Sampling Analysis:")
    print(f"  Average cycles per sample: {avg_cycles_per_sample:.2f}")
    print(f"  Standard deviation: {std_cycles_per_sample:.2f}")
    print(f"  Calculated sampling rate: {actual_sampling_rate:.0f} Hz")
    print(f"  Sample period: {1/actual_sampling_rate*1000000:.2f} µs")
    
    return actual_sampling_rate, avg_cycles_per_sample

def find_edges(samples):
    """Convert continuous samples to edge transitions"""
    edges = []
    if not samples:
        return edges
    
    prev_level = samples[0][1]
    for timestamp, level in samples[1:]:
        if level != prev_level:
            edge_type = 'rising' if level > prev_level else 'falling'
            edges.append((edge_type, timestamp))
            prev_level = level
    
    return edges

def get_level_at_time(samples, target_time):
    """Get signal level at a specific time from continuous samples"""
    if not samples:
        return 0
    
    # Find the sample at or before target_time
    for i, (timestamp, level) in enumerate(samples):
        if timestamp > target_time:
            if i == 0:
                return samples[0][1]
            return samples[i-1][1]
    
    # If target_time is after all samples, return last level
    return samples[-1][1]

# ========== UART DECODER ==========
def decode_uart_polling(channel_data, channel_name, baud_rate, data_bits=8, parity='N', stop_bits=1):
    """Decode UART using actual sampling rate from CSV data"""
    
    if channel_name not in channel_data:
        print(f"Channel {channel_name} not found in data")
        return
    
    # Calculate actual sampling rate
    sampling_info = calculate_actual_sampling_rate(channel_data)
    if not sampling_info:
        print("Could not determine sampling rate")
        return
    
    actual_sampling_rate, avg_cycles_per_sample = sampling_info
    
    samples = channel_data[channel_name]
    
    # Calculate bit time in CPU cycles and samples
    CPU_FREQ_HZ = 72_000_000
    bit_time_cycles = CPU_FREQ_HZ / baud_rate
    bit_time_samples = bit_time_cycles / avg_cycles_per_sample
    
    print(f"\nDecoding UART on {channel_name}")
    print(f"Baud rate: {baud_rate}")
    print(f"Theoretical bit time: {bit_time_cycles:.0f} cycles ({bit_time_cycles/CPU_FREQ_HZ*1000000:.1f}µs)")
    print(f"Bit time in samples: {bit_time_samples:.2f} samples")
    
    # Find edges for frame detection
    edges = find_edges(samples)
    
    # Detect UART frames (look for falling edges that could be start bits)
    frame_starts = []
    min_idle_time_samples = bit_time_samples * 0.8
    
    for i, (edge_type, timestamp) in enumerate(edges):
        if edge_type == 'falling':
            # Check if line was idle before this
            if i == 0:
                frame_starts.append(timestamp)
            else:
                # Check time since last edge
                time_since_last = timestamp - edges[i-1][1]
                samples_since_last = time_since_last / avg_cycles_per_sample
                
                if samples_since_last > min_idle_time_samples:
                    # Verify it's a valid start bit
                    next_rising = None
                    for j in range(i+1, len(edges)):
                        if edges[j][0] == 'rising':
                            next_rising = edges[j][1]
                            break
                    
                    if next_rising:
                        start_bit_duration = (next_rising - timestamp) / avg_cycles_per_sample
                        if start_bit_duration >= bit_time_samples * 0.5:
                            frame_starts.append(timestamp)
    
    print(f"Found {len(frame_starts)} potential UART frames")
    
    # Decode each frame
    decoded_bytes = []
    for start_time in frame_starts:
        try:
            # Sample data bits at bit centers
            bits = []
            for bit_index in range(data_bits):
                # Sample at 1.5 bit times + bit_index * bit_time from start
                sample_time = start_time + int(avg_cycles_per_sample * bit_time_samples * (1.5 + bit_index))
                bit_value = get_level_at_time(samples, sample_time)
                bits.append(bit_value)
            
            # Handle parity if enabled
            parity_ok = True
            if parity.upper() in ('E', 'O'):
                parity_sample_time = start_time + int(avg_cycles_per_sample * bit_time_samples * (1.5 + data_bits))
                parity_bit = get_level_at_time(samples, parity_sample_time)
                
                data_ones = sum(bits)
                if parity.upper() == 'E':
                    parity_ok = (data_ones % 2) == (1 - parity_bit)
                else:
                    parity_ok = (data_ones % 2) == parity_bit
            
            # Check stop bit
            stop_bit_offset = 1.5 + data_bits + (1 if parity != 'N' else 0)
            stop_sample_time = start_time + int(avg_cycles_per_sample * bit_time_samples * stop_bit_offset)
            stop_bit = get_level_at_time(samples, stop_sample_time)
            
            # Compose byte (LSB first for UART)
            byte_value = 0
            for idx, bit_val in enumerate(bits):
                byte_value |= (bit_val << idx)
            
            decoded_bytes.append(byte_value)
            
            # Report timing info for first few frames
            if len(decoded_bytes) <= 3:
                start_time_us = start_time / CPU_FREQ_HZ * 1000000
                print(f"  Frame {len(decoded_bytes)}: Start at {start_time_us:.1f}µs, Byte: 0x{byte_value:02X} ('{chr(byte_value) if 32 <= byte_value < 127 else '.'}')")
                print(f"    Bits: {' '.join(str(b) for b in bits)}")
            
            if not parity_ok:
                print(f"  WARNING: Parity error at {start_time/CPU_FREQ_HZ*1000000:.1f}µs")
            if stop_bit != 1:
                print(f"  WARNING: Stop bit error at {start_time/CPU_FREQ_HZ*1000000:.1f}µs")
                
        except Exception as e:
            print(f"Error decoding frame at {start_time/CPU_FREQ_HZ*1000000:.1f}µs: {e}")
    
    # Output results
    print(f"\n{'='*50}")
    print(f"UART Decode Results - Channel {channel_name}")
    print(f"{'='*50}")
    print(f"Configuration:")
    print(f"  Baud rate: {baud_rate}")
    print(f"  Data bits: {data_bits}, Parity: {parity}, Stop bits: {stop_bits}")
    print(f"  Actual sampling rate: {actual_sampling_rate:.0f} Hz")
    print(f"  Bit time: {bit_time_samples:.2f} samples")
    print(f"")
    print(f"Decoded {len(decoded_bytes)} bytes:")
    print(f"Hex:   {' '.join(f'{b:02X}' for b in decoded_bytes)}")
    print(f"ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes)}")
    
    # Save results
    output_file = f"{channel_name}_uart_decoded.txt"
    with open(output_file, 'w') as f:
        f.write(f"UART Decode Results - Channel {channel_name}\n")
        f.write(f"Baud: {baud_rate}, Data: {data_bits}, Parity: {parity}, Stop: {stop_bits}\n")
        f.write(f"Actual sampling rate: {actual_sampling_rate:.0f} Hz\n")
        f.write(f"Bit time: {bit_time_samples:.2f} samples\n")
        f.write("=" * 50 + "\n")
        f.write(f"Hex:   {' '.join(f'{b:02X}' for b in decoded_bytes)}\n")
        f.write(f"ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes)}\n")
    
    print(f"Results saved to: {output_file}")

# ========== SPI DECODER ==========
def decode_spi_polling(channel_data, clk_channel, mosi_channel, miso_channel, clock_polarity=0, clock_phase=0):
    """Decode SPI from continuous sampling data"""
    
    required_channels = [clk_channel, mosi_channel, miso_channel]
    for ch in required_channels:
        if ch not in channel_data:
            print(f"Channel {ch} not found in data")
            return
    
    clk_samples = channel_data[clk_channel]
    mosi_samples = channel_data[mosi_channel]
    miso_samples = channel_data[miso_channel]
    
    print(f"Decoding SPI: CLK={clk_channel}, MOSI={mosi_channel}, MISO={miso_channel}")
    print(f"Clock polarity: {clock_polarity}, Clock phase: {clock_phase}")
    
    # Find clock edges
    clk_edges = find_edges(clk_samples)
    
    # Determine sampling edge
    if clock_polarity == 0:
        sample_edge = 'rising' if clock_phase == 0 else 'falling'
    else:
        sample_edge = 'falling' if clock_phase == 0 else 'rising'
    
    # Find sampling edges
    sample_times = [timestamp for edge_type, timestamp in clk_edges if edge_type == sample_edge]
    
    print(f"Found {len(sample_times)} sampling edges")
    
    # Sample data at each clock edge
    mosi_bytes = []
    miso_bytes = []
    current_mosi = 0
    current_miso = 0
    bit_count = 0
    
    for sample_time in sample_times:
        mosi_bit = get_level_at_time(mosi_samples, sample_time)
        miso_bit = get_level_at_time(miso_samples, sample_time)
        
        # SPI is MSB first
        current_mosi = (current_mosi << 1) | mosi_bit
        current_miso = (current_miso << 1) | miso_bit
        bit_count += 1
        
        if bit_count == 8:
            mosi_bytes.append(current_mosi)
            miso_bytes.append(current_miso)
            print(f"SPI byte at {cycles_to_microseconds(sample_time):.1f}µs: MOSI=0x{current_mosi:02X}, MISO=0x{current_miso:02X}")
            current_mosi = 0
            current_miso = 0
            bit_count = 0
    
    # Output results
    print(f"\n{'='*20} SPI Results {'='*20}")
    print(f"MOSI Hex: {' '.join(f'{b:02X}' for b in mosi_bytes)}")
    print(f"MOSI ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in mosi_bytes)}")
    print(f"MISO Hex: {' '.join(f'{b:02X}' for b in miso_bytes)}")
    print(f"MISO ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in miso_bytes)}")
    
    # Save results
    with open("spi_decoded.txt", "w") as f:
        f.write("=== SPI Decoded Data ===\n")
        f.write(f"CLK: {clk_channel}, MOSI: {mosi_channel}, MISO: {miso_channel}\n")
        f.write(f"Clock polarity: {clock_polarity}, Clock phase: {clock_phase}\n")
        f.write(f"CPU Frequency: {CPU_FREQ_HZ:,} Hz\n")
        f.write("=" * 50 + "\n")
        f.write(f"MOSI Hex: {' '.join(f'{b:02X}' for b in mosi_bytes)}\n")
        f.write(f"MOSI ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in mosi_bytes)}\n")
        f.write(f"MISO Hex: {' '.join(f'{b:02X}' for b in miso_bytes)}\n")
        f.write(f"MISO ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in miso_bytes)}\n")
    
    print("Results saved to: spi_decoded.txt")

# ========== I2C DECODER ==========
def decode_i2c_polling(channel_data, scl_channel, sda_channel):
    """Decode I2C from continuous sampling data"""
    
    if scl_channel not in channel_data or sda_channel not in channel_data:
        print(f"Required channels not found in data")
        return
    
    scl_samples = channel_data[scl_channel]
    sda_samples = channel_data[sda_channel]
    
    print(f"Decoding I2C: SCL={scl_channel}, SDA={sda_channel}")
    
    # Find edges
    scl_edges = find_edges(scl_samples)
    sda_edges = find_edges(sda_samples)
    
    # Detect start/stop conditions (SDA changes while SCL is high)
    start_stop_conditions = []
    
    for edge_type, timestamp in sda_edges:
        scl_level = get_level_at_time(scl_samples, timestamp)
        if scl_level == 1:  # SCL is high
            if edge_type == 'falling':
                start_stop_conditions.append(('START', timestamp))
            elif edge_type == 'rising':
                start_stop_conditions.append(('STOP', timestamp))
    
    # Sample data on SCL rising edges
    scl_rising_times = [timestamp for edge_type, timestamp in scl_edges if edge_type == 'rising']
    
    decoded_bytes = []
    current_byte = 0
    bit_count = 0
    
    for sample_time in scl_rising_times:
        sda_bit = get_level_at_time(sda_samples, sample_time)
        
        # I2C is MSB first
        current_byte = (current_byte << 1) | sda_bit
        bit_count += 1
        
        if bit_count == 8:
            decoded_bytes.append(current_byte)
            print(f"I2C byte at {cycles_to_microseconds(sample_time):.1f}µs: 0x{current_byte:02X}")
            current_byte = 0
            bit_count = 0
    
    # Output results
    print(f"\n{'='*20} I2C Results {'='*20}")
    for condition, timestamp in start_stop_conditions:
        print(f"I2C {condition} at {cycles_to_microseconds(timestamp):.1f}µs")
    
    print(f"Decoded bytes: {' '.join(f'{b:02X}' for b in decoded_bytes)}")
    print(f"ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes)}")
    
    # Save results
    with open("i2c_decoded.txt", "w") as f:
        f.write("=== I2C Decoded Data ===\n")
        f.write(f"SCL: {scl_channel}, SDA: {sda_channel}\n")
        f.write(f"CPU Frequency: {CPU_FREQ_HZ:,} Hz\n")
        f.write("=" * 50 + "\n")
        
        for condition, timestamp in start_stop_conditions:
            f.write(f"I2C {condition} at {cycles_to_microseconds(timestamp):.1f}µs\n")
        
        f.write(f"Hex: {' '.join(f'{b:02X}' for b in decoded_bytes)}\n")
        f.write(f"ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded_bytes)}\n")
    
    print("Results saved to: i2c_decoded.txt")

# ========== MAIN FUNCTION ==========
def main():
    if len(sys.argv) != 3:
        print("Usage: python polling_decoder.py <protocol> <csv_file>")
        print("Supported protocols: uart, spi, i2c")
        sys.exit(1)
    
    protocol = sys.argv[1].lower()
    csv_file = sys.argv[2]
    
    # Load data
    channel_data = load_csv_data(csv_file)
    if not channel_data:
        return
    
    print(f"Available channels: {list(channel_data.keys())}")
    
    try:
        if protocol == 'uart':
            print("\nUART Decoder Configuration:")
            channel = input(f"Enter UART channel name from {list(channel_data.keys())}: ")
            baud = int(input("Enter UART baud rate (e.g., 9600): "))
            data_bits = int(input("Enter number of data bits (7 or 8): "))
            parity = input("Enter parity (N = none, E = even, O = odd): ").upper()
            stop_bits = int(input("Enter number of stop bits (1 or 2): "))
            decode_uart_polling(channel_data, channel, baud, data_bits, parity, stop_bits)
            
        elif protocol == 'spi':
            print("\nSPI Decoder Configuration:")
            clk_ch = input(f"Enter CLK channel name from {list(channel_data.keys())}: ")
            mosi_ch = input(f"Enter MOSI channel name from {list(channel_data.keys())}: ")
            miso_ch = input(f"Enter MISO channel name from {list(channel_data.keys())}: ")
            clock_pol = int(input("Enter clock polarity (0 = idle low, 1 = idle high): "))
            clock_phase = int(input("Enter clock phase (0 = sample on leading edge, 1 = trailing edge): "))
            decode_spi_polling(channel_data, clk_ch, mosi_ch, miso_ch, clock_pol, clock_phase)
            
        elif protocol == 'i2c':
            print("\nI2C Decoder Configuration:")
            scl_ch = input(f"Enter SCL channel name from {list(channel_data.keys())}: ")
            sda_ch = input(f"Enter SDA channel name from {list(channel_data.keys())}: ")
            decode_i2c_polling(channel_data, scl_ch, sda_ch)
            
        else:
            print("Unsupported protocol. Use 'uart', 'spi', or 'i2c'.")
            
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()