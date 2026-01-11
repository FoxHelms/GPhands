import socket
import struct
import numpy as np
import cv2
import time
from datetime import datetime, timedelta


# Configuration
UDP_IP = "*********"
UDP_PORT = *****
MAX_PKT_SIZE = 65535  

# change this to frame header
HEADER_FORMAT = "<IHHIfH"   # magic, width, height, frame_id, fps, total_packets
HEADER_SIZE = struct.calcsize(HEADER_FORMAT) # = 18 bytes

PACKET_HEADER_FORMAT = "<II"
PACKET_HEADER_SIZE = struct.calcsize(PACKET_HEADER_FORMAT)


MAGIC = '0xdeadbeef'
CAM_ADDR = "********"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024)
sock.bind(("*******", 5000))

frames_counted = 0
framerates_collected = 0.0

buf = bytearray(65535)
nbytes = 0

# Buffer to store frame chunks: { frame_id: { metadata: { timestamp: {} }, packets: { packet_ind : img_data} }
frames = {}
frame_id = 0
expected_packets = 0
written_packets = 0

cv2.namedWindow("stream", cv2.WINDOW_NORMAL)

def process_header(packet):
    global expected_packets, written_packets
    magic, width, height, frame_id, fps, total_packets = struct.unpack_from(
        HEADER_FORMAT, data, 0
    )
    if hex(magic) == MAGIC:
        if frame_id not in frames:
            time_stamp = datetime.fromtimestamp(time.time())
            frames[frame_id] = { 'metadata' : { 'timestamp' : time_stamp }, 'packets' : {} }
            expected_packets = total_packets
            written_packets = 0


def write_frame(packet):
    global frames, PACKET_HEADER_SIZE, written_packets
    frame_id, packet_ind = struct.unpack_from(
        PACKET_HEADER_FORMAT, packet, 0
    )
    if frames.get(frame_id):
        frames[frame_id]['packets'][packet_ind] = packet[PACKET_HEADER_SIZE:].tobytes()
    else:
        time_stamp = datetime.fromtimestamp(time.time())
        frames[frame_id] = { 'metadata' : { 'timestamp' : time_stamp }, 'packets' : { packet_ind : packet[PACKET_HEADER_SIZE:].tobytes() } }

    written_packets += 1

def sort_frame(frame_id):
    return sorted(frames.get(frame_id).get('packets'))

def build_frame(frame_id):
    global frames
    return b"".join(frames.get(frame_id).get('packets')[packet_ind] for packet_ind in sort_frame(frame_id))

def show_frame(frame_id):
    global frames, expected_packets, written_packets
    img_arr = np.frombuffer(build_frame(frame_id), dtype=np.uint8)
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

    # Clear frames: even working?
    frames = {}
    frame_id = 0
    expected_packets = 0
    written_packets = 0

def last_packet(data):
    return (written_packets == expected_packets and data[PACKET_HEADER_SIZE:].tobytes().endswith(b'\xff\xd9'))

def prune_frames(frames, ts):
    time_cutoff = ts - timedelta(seconds=2)
    for k in list(frames):
        if frames[k]["metadata"]["timestamp"] < time_cutoff:
            del frames[k]


print("Listening...")

try:
    while True:
        try:
            nbytes, ancdata, msg_flags, addr = sock.recvmsg_into([buf])
            data = memoryview(buf)[:nbytes]
        except BlockingIOError:
            pass

        if addr[0] != CAM_ADDR:
            continue

        # CREATE FRAME OBJECT
        if nbytes == ( HEADER_SIZE + 2 ):
            process_header(data)
            continue

        if nbytes > ( HEADER_SIZE + 2 ):
            cur_frame_id, packet_ind = struct.unpack_from(
                PACKET_HEADER_FORMAT, data, 0
            )
            write_frame(data)
            end_of_image = data[-10:].tobytes().endswith(b'\xff\xd9')
            print(f'received packets: {written_packets} / {expected_packets}')
            if last_packet(data) and cur_frame_id == max(frames):
                print(f'calling show frame: {cur_frame_id}')
                show_frame(cur_frame_id)
            cv2.waitKey(10)
            prune_frames(frames, datetime.fromtimestamp(time.time()))
            continue
except KeyboardInterrupt:
    pass
finally:
    sock.close()
    cv2.destroyAllWindows()
