#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include "camera_index.h"
#include "board_config.h"

const char *ssid = "********";
const char *password = "********";
WiFiUDP udp;
const char* udpAddress = "********";
const int udpPort = 5000;
float ra_avg_us = 0;
const float alpha = 0.9f;
#define UDP_FRAME_MAGIC 0xDEADBEEF

#define MAX_QVGA_JPEG 20000
#define UDP_CHUNK 1400
void setupLedFlash();

float ra_filter_us(float frame_time_us) {
  if (ra_avg_us == 0) {
    ra_avg_us = frame_time_us;
  } else {
    ra_avg_us = ra_avg_us * alpha + frame_time_us * (1.0f - alpha);
  }
  return ra_avg_us;
}

struct UdpFrameHeader {
  uint32_t magic;
  uint16_t width;
  uint16_t height;
  uint32_t frame_id;
  float fps;
};

struct UdpPacketHeader {
  uint32_t frame_id;
  uint32_t packet_index;
};

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;  //20000000
  config.frame_size = FRAMESIZE_QVGA;
  config.pixel_format = PIXFORMAT_JPEG;  // for streaming
  config.jpeg_quality = 8; //12
  //config.pixel_format = PIXFORMAT_RGB565; // for face detection/recognition
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.fb_count = 2;

  Serial.printf("PSRAM: %s", psramFound() ? "OK" : "FAIL");
  Serial.println();

  // camera init
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }

  sensor_t *s = esp_camera_sensor_get();
  // initial sensors are flipped vertically and colors are a bit saturated
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);        // flip it back
    s->set_brightness(s, 1);   // up the brightness just a bit
    s->set_saturation(s, -2);  // lower the saturation
  }

// Setup LED FLash if LED pin is defined in camera_pins.h
#if defined(LED_GPIO_NUM)
  setupLedFlash();
#endif

  WiFi.begin(ssid, password);
  WiFi.setSleep(false);

  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected");

  udp.begin(udpPort);

  Serial.println("Now sending UDP packets");
  Serial.print("sent packets:");

}

void loop() {
  camera_fb_t *fb = NULL;
  struct timeval _timestamp;
  esp_err_t res = ESP_OK;
  static int64_t last_frame = esp_timer_get_time();
  static uint32_t frame_id = 0;

  fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    res = ESP_FAIL;
    return;
  }
  if (fb) {
    _timestamp.tv_sec = fb->timestamp.tv_sec;
    _timestamp.tv_usec = fb->timestamp.tv_usec;
  }
  if (res == ESP_OK) {
    int64_t fr_end = esp_timer_get_time();
    int64_t frame_time = fr_end - last_frame;
    last_frame = fr_end;

    frame_time /= 1000;
    uint32_t avg_frame_time = ra_filter_us(frame_time);
    float fps = 1000.0 / avg_frame_time;

    UdpFrameHeader header;
    header.magic = UDP_FRAME_MAGIC;
    header.width = fb->width;
    header.height = fb->height;
    header.frame_id = frame_id++;
    header.fps = fps;
    size_t len = fb->len;
    size_t sent = 0;
    udp.beginPacket(udpAddress, udpPort);
    udp.write((uint8_t*)&header, sizeof(header));
    udp.endPacket();
    udp.beginPacket(udpAddress, udpPort);
    while (sent < len) {
      size_t remaining = len - sent;
      size_t chunk = (remaining < UDP_CHUNK ) ? remaining : UDP_CHUNK;
      udp.write(fb->buf + sent, chunk);
      sent += chunk;
    }
    udp.endPacket();
    Serial.println("Sent image");

    esp_camera_fb_return(fb);
    fb = NULL;
    delay(5);
  }
}
