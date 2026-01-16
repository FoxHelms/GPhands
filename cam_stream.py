import socket
import struct
import numpy as np
import cv2
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

# Configuration
UDP_IP = os.getenv("UDP_IP")
UDP_PORT = 5000
MAX_PKT_SIZE = 65535

# change this to frame header
HEADER_FORMAT = os.getenv("HEADER_FORMAT")   # magic, width, height, frame_id, fps, total_packets
HEADER_SIZE = struct.calcsize(HEADER_FORMAT) # = 18 bytes

PACKET_HEADER_FORMAT = os.getenv("PACKET_HEADER_FORMAT")
PACKET_HEADER_SIZE = struct.calcsize(PACKET_HEADER_FORMAT)


MAGIC = '0xdeadbeef'
CAM_ADDR = os.getenv("CAM_ADDR")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024)
sock.bind((UDP_IP, 5000))
sock.setblocking(False)

frames_counted = 0

buf = bytearray(65535)
nbytes = 0




# HELPER FUNCTIONS

def last_packet(data):
    return (data[-10:].tobytes().endswith(b'\xff\xd9'))

def process_header(packet):
    global expected_packets, written_packets
    if not packet:
        return None
    magic, width, height, frame_id, fps, total_packets = struct.unpack_from(
        HEADER_FORMAT, packet, 0
    )
    # print(f'processing header for frame {frame_id}')
    if hex(magic) == MAGIC:
        timestamp = datetime.fromtimestamp(time.time())
        return frame_id, total_packets, timestamp

def process_packet(packet):
    if not packet:
        return None
    frame_id, packet_ind = struct.unpack_from(
        PACKET_HEADER_FORMAT, packet, 0
    )
    timestamp = datetime.fromtimestamp(time.time())
    return frame_id, packet_ind, timestamp

def write_frame(frame_id, packet_index, data, frame_buffer):
    global frames, PACKET_HEADER_SIZE, written_packets
    # print(f' writing frame: {frame_id}')
    if frame_buffer.get(frame_id):
        frame_buffer[frame_id]['packets'][packet_ind] = data[PACKET_HEADER_SIZE:].tobytes()
    else:
        time_stamp = datetime.fromtimestamp(time.time())
        frame_buffer[frame_id] = { 'metadata' : { 'timestamp' : time_stamp }, 'packets' : { packet_ind : data[PACKET_HEADER_SIZE:].tobytes() } }

    written_packets += 1

def show_frame(frame_id, frame_buffer):
    global expected_packets, written_packets, total_packets
    # print(f'Showing frame {frame_id}')
    img_arr = np.frombuffer(build_frame(frame_buffer), dtype=np.uint8)
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    org = (50, 50) # Bottom-left corner of the text string
    font = cv2.FONT_HERSHEY_SIMPLEX
    fontScale = 1
    color = (0, 255, 0) # Green color in BGR format
    thickness = 2
    lineType = cv2.LINE_AA # For a smoother line

    if img is not None:
        cv2.putText(img, str(frame_id), org, font, fontScale, color, thickness, lineType)
        cv2.imshow("stream", img)
        total_packets += 1

def shuffle_buffers(current_buffer, next_buffer):
    current_buffer = next_buffer
    next_buffer = {}
    return current_buffer, next_buffer

def sort_frame(frame_buffer):
    # print(f'converting to dict: {frames.get(frame_id)}')
    return sorted(frame_buffer.get(list(frame_buffer.keys())[0]).get('packets'))

def build_frame(frame_buffer):
    return b"".join(frame_buffer.get(list(frame_buffer.keys())[0]).get('packets')[packet_ind] for packet_ind in sort_frame(frame_buffer))


# INIT EVERYTHING

# Buffer to store frame chunks: 
# { frame_id: { metadata: { timestamp: {} }, packets: { packet_ind : img_data} }

build_buffer = {}
scratchpad = {}
display_buffer = {}

curr_frame_id = 0
total_frames = 0
written_packets = 0
MAX_AGE_SECONDS = 1
HOLDOFF_TIMESTAMP = None
HOLDOFF_SECONDS = 2

cv2.namedWindow("stream", cv2.WINDOW_NORMAL)
cv2.imshow("stream", np.zeros((160, 120, 3), dtype=np.uint8))

print("Listening...")
start_stream = time.time()
try:
    while True:
        addr = None
        try:
            while True:
                nbytes, ancdata, msg_flags, addr = sock.recvmsg_into([buf])
                data = memoryview(buf)[:nbytes]
        except BlockingIOError:
            pass


        # NO PACKET
        if not addr or not data:
            continue

        # HEADER PACKET
        if nbytes == ( HEADER_SIZE + 2 ):
            frame_id, total_packets, timestamp = process_header(data)
            # print(f"header{frame_id}")
            continue

        # PAYLOAD PACKET
        if nbytes > ( HEADER_SIZE + 2 ):
            frame_id, packet_ind, timestamp = process_packet(data)
            # print(f"packet for {frame_id}")
            if curr_frame_id == 0:
                cur_frame_id = frame_id

            # QUICK FIX FOR WRAPAROUND
            if curr_frame_id >= 590:
                build_buffer = {}
                scratchpad = {}
                curr_frame_id = 0
                continue

            # DUMP OLD FRAMES
            if frame_id < curr_frame_id:
                continue
            # BUILD CURRENT FRAME
            if frame_id == curr_frame_id:
                if HOLDOFF_TIMESTAMP:
                    if (timestamp - HOLDOFF_TIMESTAMP) <= timedelta(seconds=HOLDOFF_SECONDS):
                        write_frame(frame_id, packet_ind, data, build_buffer)
                        if last_packet(data):
                            if len(build_buffer) != 0:
                                show_frame(frame_id, build_buffer)
                                build_buffer, scratchpad = shuffle_buffers(build_buffer, scratchpad)
                                curr_frame_id = list(build_buffer.keys())[0] if build_buffer else 0
                            continue
                    else:
                        write_frame(frame_id, packet_ind, data, build_buffer)
                        show_frame(frame_id, build_buffer)
                        build_buffer, scratchpad = shuffle_buffers(build_buffer, scratchpad)
                        # if the scratchpad was empty, reset the curr_frame_id
                        curr_frame_id = list(build_buffer.keys())[0] if build_buffer else 0 
                        continue
                else:
                    write_frame(frame_id, packet_ind, data, build_buffer)
                    if last_packet(data):
                        show_frame(frame_id, build_buffer)
                        build_buffer, scratchpad = shuffle_buffers(build_buffer, scratchpad)
                

            # CHECK FOR BURST
            if frame_id >= (curr_frame_id + 5):
                if build_buffer:
                    show_frame(curr_frame_id, build_buffer)
                    build_buffer, scratchpad = shuffle_buffers(build_buffer, scratchpad) # becomes: {...}, {}
                    if build_buffer:
                        show_frame(list(build_buffer.keys())[0], build_buffer)
                        build_buffer = {}
                
                write_frame(frame_id, packet_ind, data, build_buffer)
                curr_frame_id = list(build_buffer.keys())[0]
                continue

            # BUILD NEXT FRAME
            if frame_id == (curr_frame_id + 1):
                write_frame(frame_id, packet_ind, data, scratchpad)
                if not HOLDOFF_TIMESTAMP:
                    HOLDOFF_TIMESTAMP = timestamp
                continue


            
            cv2.waitKey(10)

            continue

except KeyboardInterrupt:
    pass
finally:
    sock.close()
    cv2.destroyAllWindows()
    end_stream = time.time()
    print(f'Avg FPS for session: {total_frames / (end_stream - start_stream)}')
