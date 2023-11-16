import os
import sys
import time
import struct
import board
from digitalio import DigitalInOut, Direction, Pull
from adafruit_debouncer import Debouncer, Button
import bitmaptools
import busio
import adafruit_lis3dh
import neopixel
from rainbowio import colorwheel
import sdcardio
import storage
import displayio
import espcamera
from adafruit_st7789 import ST7789
import terminalio
from adafruit_display_text import label
import pwmio
import microcontroller
import adafruit_aw9523
from adafruit_bus_device.i2c_device import I2CDevice
from rainbowio import colorwheel

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_PyCamera.git"

from micropython import const

_REG_DLY = const(0xFFFF)

_OV5640_STAT_FIRMWAREBAD = const(0x7F)
_OV5640_STAT_STARTUP = const(0x7E)
_OV5640_STAT_IDLE = const(0x70)
_OV5640_STAT_FOCUSING = const(0x00)
_OV5640_STAT_FOCUSED = const(0x10)

_OV5640_CMD_TRIGGER_AUTOFOCUS = const(0x03)
_OV5640_CMD_AUTO_AUTOFOCUS = const(0x04)
_OV5640_CMD_RELEASE_FOCUS = const(0x08)

_OV5640_CMD_MAIN = const(0x3022)
_OV5640_CMD_ACK = const(0x3023)
_OV5640_CMD_PARA0 = const(0x3024)
_OV5640_CMD_PARA1 = const(0x3025)
_OV5640_CMD_PARA2 = const(0x3026)
_OV5640_CMD_PARA3 = const(0x3027)
_OV5640_CMD_PARA4 = const(0x3028)
_OV5640_CMD_FW_STATUS = const(0x3029)

class PyCamera:
    _finalize_firmware_load = (
            0x3022, 0x00,
            0x3023, 0x00,
            0x3024, 0x00,
            0x3025, 0x00,
            0x3026, 0x00,
            0x3027, 0x00,
            0x3028, 0x00,
            0x3029, 0x7f,
            0x3000, 0x00,
    )
    led_levels = [0., .1, .2, .5, 1.]

    colors = [0xffffff, 0xff0000, 0xffff00, 0x00ff00, 0x00ffff, 0x0000ff, 0xff00ff,
        [colorwheel(i*(256//8)) for i in range(8)]]

    resolutions = (
        #"160x120",
        #"176x144",
        #"240x176",
        "240x240",
        "320x240",
        #"400x296",
        #"480x320",
        "640x480",
        "800x600",
        "1024x768",
        "1280x720",
        "1280x1024",
        "1600x1200",
        "1920x1080",
        #"720x1280",
        #"864x1536",
        "2048x1536",
        "2560x1440",
        "2560x1600",
        #"1080x1920",
        "2560x1920",
    )
    resolution_to_frame_size = (
        #espcamera.FrameSize.QQVGA,
        #espcamera.FrameSize.QCIF,
        #espcamera.FrameSize.HQVGA,
        espcamera.FrameSize.R240X240, # 240x240
        espcamera.FrameSize.QVGA, # 320x240
        #espcamera.FrameSize.CIF, # 400x296
        #espcamera.FrameSize.HVGA, # 480x320
        espcamera.FrameSize.VGA,   #  640x480
        espcamera.FrameSize.SVGA, # 800x600
        espcamera.FrameSize.XGA, # 1024x768
        espcamera.FrameSize.HD, # 1280x720 
        espcamera.FrameSize.SXGA, # 1280x1024
        espcamera.FrameSize.UXGA, # 1600x1200
        espcamera.FrameSize.FHD, # 1920x1080
        #espcamera.FrameSize.P_HD, # 720x1280
        # espcamera.FrameSize.P_3MP, # 864x1536
        espcamera.FrameSize.QXGA, # 2048x1536
        espcamera.FrameSize.QHD, # 2560x1440
        espcamera.FrameSize.WQXGA, # 2560x1600
        #espcamera.FrameSize.P_FHD, # 1080x1920
        espcamera.FrameSize.QSXGA, # 2560x1920
    )
    combined_list = list(zip(resolutions, resolution_to_frame_size))
    print(combined_list)

    effects = ("Normal", "Invert", "B&W", "Reddish", "Greenish", "Bluish", "Sepia", "Solarize")
    modes = ("JPEG", "GIF", "STOP")
    
    _AW_MUTE =   const(0)
    _AW_SELECT =   const(1)
    _AW_CARDDET =   const(8)
    _AW_SDPWR =   const(9)
    _AW_DOWN = const(15)
    _AW_LEFT =  const(14)
    _AW_UP =  const(13)
    _AW_RIGHT =   const(12)
    _AW_OK =   const(11)
    #_SS_ALL_BUTTONS_MASK = const(0b000010000000001011100)
    #_SS_DOWN_MASK = const(0x10000)
    #_SS_LEFT_MASK = const(0x00004)
    #_SS_UP_MASK = const(0x00008)
    #_SS_RIGHT_MASK = const(0x00040)
    #_SS_CARDDET_MASK = const(0x00010)

    _NVM_RESOLUTION = const(1)
    _NVM_EFFECT = const(2)
    _NVM_MODE = const(3)
    
    _INIT_SEQUENCE = (
        b"\x01\x80\x78"  # _SWRESET and Delay 120ms
        b"\x11\x80\x05"  # _SLPOUT and Delay 5ms
        b"\x3A\x01\x55"  # _COLMOD
        b"\x21\x00"      # _INVON Hack
        b"\x13\x00"      # _NORON
        b"\x36\x01\xA0"  # _MADCTL
        b"\x29\x80\x05"  # _DISPON and Delay 5ms
        )

    def i2c_scan(self):
        while not self._i2c.try_lock():
            pass

        try:
            print("I2C addresses found:",
                    [hex(device_address) for device_address in self._i2c.scan()],
                )
        finally:  # unlock the i2c bus when ctrl-c'ing out of the loop
            self._i2c.unlock()
    

    def __init__(self) -> None:
        self.t = time.monotonic()
        self._i2c = board.I2C()
        self._spi = board.SPI()
        self.deinit_display()

        self.splash = displayio.Group()
        self._sd_label = label.Label(terminalio.FONT, text="SD ??", color=0x0, x=150, y=10, scale=2)
        self._effect_label = label.Label(terminalio.FONT, text="EFFECT", color=0xFFFFFF, x=4, y=10, scale=2)
        self._mode_label = label.Label(terminalio.FONT, text="MODE", color=0xFFFFFF, x=150, y=10, scale=2)

        # turn on the display first, its reset line may be shared with the IO expander(?)
        if not self.display:
            self.init_display()

        self.shutter_button = DigitalInOut(board.BUTTON)
        self.shutter_button.switch_to_input(Pull.UP)
        self.shutter = Button(self.shutter_button)

        print("reset camera")
        self._cam_reset = DigitalInOut(board.CAMERA_RESET)
        self._cam_pwdn = DigitalInOut(board.CAMERA_PWDN)

        self._cam_reset.switch_to_output(False)
        self._cam_pwdn.switch_to_output(True)
        time.sleep(0.01)
        self._cam_pwdn.switch_to_output(False)
        time.sleep(0.01)
        self._cam_reset.switch_to_output(True)
        time.sleep(0.01)

        print("pre cam @", time.monotonic()-self.t)
        self.i2c_scan()

        # AW9523 GPIO expander
        self._aw = adafruit_aw9523.AW9523(self._i2c, address=0x58)
        print("Found AW9523")

        def make_expander_input(pin_no):
            pin = self._aw.get_pin(pin_no)
            pin.switch_to_input()
            return pin

        def make_expander_output(pin_no, value):
            pin = self._aw.get_pin(pin_no)
            pin.switch_to_output(value)
            return pin

        def make_debounced_expander_pin(pin_no):
            pin = self._aw.get_pin(pin_no)
            pin.switch_to_input()
            return Debouncer(make_expander_input(pin_no))


        self.up = make_debounced_expander_pin(_AW_UP)
        self.left = make_debounced_expander_pin(_AW_LEFT)
        self.right = make_debounced_expander_pin(_AW_RIGHT)
        self.down = make_debounced_expander_pin(_AW_DOWN)
        self.select = make_debounced_expander_pin(_AW_SELECT)
        self.ok = make_debounced_expander_pin(_AW_OK)
        self.card_detect = make_debounced_expander_pin(_AW_CARDDET)
        
        self._card_power = make_expander_output(_AW_SDPWR, True)

        self.mute = make_expander_input(_AW_MUTE)

        self.sdcard = None
        try:
            self.mount_sd_card()
        except RuntimeError:
            pass # no card found, its ok!
        print("sdcard done @", time.monotonic()-self.t)
        
        # lis3dh accelerometer
        self.accel = adafruit_lis3dh.LIS3DH_I2C(self._i2c, address=0x19)
        self.accel.range = adafruit_lis3dh.RANGE_2_G

        # main board neopixel
        neopix = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.1)
        neopix.fill(0)
        neopix.deinit()

        # front bezel neopixels
        self.pixels = neopixel.NeoPixel(board.A1, 8, brightness=0.1, pixel_order=neopixel.RGBW)
        self.pixels.fill(0)

        print("Initializing camera")
        self.camera = espcamera.Camera(
            data_pins=board.CAMERA_DATA,
            external_clock_pin=board.CAMERA_XCLK,
            pixel_clock_pin=board.CAMERA_PCLK,
            vsync_pin=board.CAMERA_VSYNC,
            href_pin=board.CAMERA_HREF,
            pixel_format=espcamera.PixelFormat.RGB565,
            frame_size=espcamera.FrameSize.HQVGA,
            i2c=board.I2C(),
            external_clock_frequency=20_000_000,
            framebuffer_count=2)
        
        print("Found camera %s (%d x %d) at I2C address %02x" % (self.camera.sensor_name, self.camera.width, self.camera.height, self.camera.address))
        print("camera done @", time.monotonic()-self.t)
        print(dir(self.camera))

        self._camera_device = I2CDevice(self._i2c, self.camera.address)
        #display.auto_refresh = False

        self.camera.hmirror = True
        self.camera.vflip = True

        self._bigbuf = None

        self._topbar = displayio.Group()
        self._res_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=0, y=10, scale=2)
        self._topbar.append(self._res_label)
        self._topbar.append(self._sd_label)

        self._botbar = displayio.Group(x=0, y=210)
        self._botbar.append(self._effect_label)
        self._botbar.append(self._mode_label)

        self.splash.append(self._topbar)
        self.splash.append(self._botbar)
        self.display.root_group = self.splash
        self.display.refresh()

        self.led_color = 0
        self.led_level = 0

        #self.camera.colorbar = True
        self.effect = microcontroller.nvm[_NVM_EFFECT]
        self.camera.saturation = 3
        self.resolution = microcontroller.nvm[_NVM_RESOLUTION]
        self.mode = microcontroller.nvm[_NVM_MODE]
        print("init done @", time.monotonic()-self.t)

    def autofocus_init_from_file(self, filename):
        with open(filename, mode='rb') as file:
            firmware = file.read()
        self.autofocus_init_from_bitstream(firmware)

    def write_camera_register(self, reg: int, value: int) -> None:
        b = bytearray(3)
        b[0] = reg >> 8
        b[1] = reg & 0xFF
        b[2] = value
        with self._camera_device as i2c:
            i2c.write(b)

    def write_camera_list(self, reg_list: Sequence[int]) -> None:
        for i in range(0, len(reg_list), 2):
            register = reg_list[i]
            value = reg_list[i + 1]
            if register == _REG_DLY:
                time.sleep(value / 1000)
            else:
                self.write_camera_register(register, value)

    def read_camera_register(self, reg: int) -> int:
        b = bytearray(2)
        b[0] = reg >> 8
        b[1] = reg & 0xFF
        with self._camera_device as i2c:
            i2c.write(b)
            i2c.readinto(b, end=1)
        return b[0]

    def autofocus_init_from_bitstream(self, firmware):
        if self.camera.sensor_name != "OV5640":
            raise RuntimeError(f"Autofocus not supported on {self.camera.sensor_name}")

        self.write_camera_register(0x3000, 0x20) # reset autofocus coprocessor

        for addr, val in enumerate(firmware):
            self.write_camera_register(0x8000+addr, val)

        self.write_camera_list(self._finalize_firmware_load)
        for _ in range(100):
            self._print_focus_status("init from bitstream")
            if self.autofocus_status == _OV5640_STAT_IDLE:
                break
            time.sleep(0.01)
        else:
            raise RuntimeError("Timed out after trying to load autofocus firmware")

    def autofocus_init(self):
        if '/' in __file__:
            binfile = __file__.rsplit("/", 1)[0].rsplit(".", 1)[0] + "/ov5640_autofocus.bin"
        else:
            binfile = "ov5640_autofocus.bin"
        print(binfile)
        return self.autofocus_init_from_file(binfile)

    @property
    def autofocus_status(self):
        return self.read_camera_register(_OV5640_CMD_FW_STATUS)

    def _print_focus_status(self, msg):
        if False:
            print(f"{msg:36} status={self.autofocus_status:02x} busy?={self.read_camera_register(_OV5640_CMD_ACK):02x}")

    def _send_autofocus_command(self, command, msg):
        self.write_camera_register(_OV5640_CMD_ACK, 0x01) # clear command ack
        self.write_camera_register(_OV5640_CMD_MAIN, command) # send command
        for _ in range(100):
            self._print_focus_status(msg)
            if self.read_camera_register(_OV5640_CMD_ACK) == 0x0: # command is finished
                return True
            time.sleep(0.01)
        else:
            return False

    def autofocus(self) -> list[int]:
        if not self._send_autofocus_command(_OV5640_CMD_RELEASE_FOCUS, "release focus"):
            return [False] * 5
        if not self._send_autofocus_command(_OV5640_CMD_TRIGGER_AUTOFOCUS, "autofocus"):
            return [False] * 5
        zone_focus = [self.read_camera_register(_OV5640_CMD_PARA0 + i) for i in range(5)]
        print(f"zones focused: {zone_focus}")
        return zone_focus

    def select_setting(self, setting_name):
        self._effect_label.color = 0xFFFFFF
        self._effect_label.background_color = 0x0
        self._res_label.color = 0xFFFFFF
        self._res_label.background_color = 0x0
        self._res_label.text = self.resolutions[self._resolution]
        self._mode_label.color = 0xFFFFFF
        self._mode_label.background_color = 0x0
        if setting_name == "effect":
            self._effect_label.color = 0x0
            self._effect_label.background_color = 0xFFFFFF
        elif setting_name == "resolution":
            self._res_label.color = 0x0
            self._res_label.background_color = 0xFFFFFF
        elif setting_name == "mode":
            self._mode_label.color = 0x0
            self._mode_label.background_color = 0xFFFFFF
        elif setting_name == "led_level":
            self._res_label.text = "LED LV"
            self._res_label.color = 0x0
            self._res_label.background_color = 0xFFFFFF
        elif setting_name == "led_color":
            self._res_label.text = "LED CLR"
            self._res_label.color = 0x0
            self._res_label.background_color = 0xFFFFFF
        self.display.refresh()

    @property
    def mode(self):
        return self._mode

    @property
    def mode_text(self):
        return self.modes[self._mode]
    
    @mode.setter
    def mode(self, setting):
        setting = (setting + len(self.modes)) % len(self.modes)
        self._mode = setting
        self._mode_label.text = self.modes[setting]
        if self.modes[setting] == "STOP":
            self.stop_motion_frame = 0
        if self.modes[setting] == "GIF":
            self._res_label.text = ""
        else:
            self.resolution = self.resolution # kick it to reset the display
        microcontroller.nvm[_NVM_MODE] = setting
        self.display.refresh()
    
    @property
    def effect(self):
        return self._effect
    
    @effect.setter
    def effect(self, setting):
        setting = (setting + len(self.effects)) % len(self.effects)
        self._effect = setting
        self._effect_label.text = self.effects[setting]
        self.camera.special_effect = setting
        microcontroller.nvm[_NVM_EFFECT] = setting
        self.display.refresh()

    @property
    def resolution(self):
        return self._resolution

    @resolution.setter
    def resolution(self, res):
        if isinstance(res, str):
            if not res in self.resolutions:
                raise RuntimeError("Invalid Resolution")
            res = self.resolutions.index(res)
        if isinstance(res, int):
            res = (res + len(self.resolutions)) % len(self.resolutions)
            microcontroller.nvm[_NVM_RESOLUTION] = res
            self._resolution = res
            self._res_label.text = self.resolutions[res]
        self.display.refresh()


    def init_display(self):
        # construct displayio by hand
        displayio.release_displays()        
        self._display_bus = displayio.FourWire(self._spi, command=board.TFT_DC,
                                               chip_select=board.TFT_CS,
                                               reset=board.TFT_RESET,
                                               baudrate=60_000_000)
        self.display = board.DISPLAY
        # init specially since we are going to write directly below
        self.display = displayio.Display(self._display_bus, self._INIT_SEQUENCE,
                                         width=240, height=240, colstart=80,
                                         auto_refresh=False)
        self.display.root_group = self.splash
        self.display.refresh()
        
    def deinit_display(self):
        # construct displayio by hand
        displayio.release_displays()
        self._display_bus = None
        self.display = None

    def display_message(self, message, color=0xFF0000, scale=3):
        text_area = label.Label(terminalio.FONT, text=message, color=color, scale=scale)
        text_area.anchor_point = (0.5, 0.5)
        if not self.display:
            self.init_display()
        text_area.anchored_position = (self.display.width / 2, self.display.height / 2)
        
        # Show it
        self.splash.append(text_area)
        self.display.refresh()
        self.splash.pop()

    def mount_sd_card(self):
        self._sd_label.text = "NO SD"
        self._sd_label.color = 0xFF0000
        if not self.card_detect.value:
            raise RuntimeError("SD card detection failed")
        if self.sdcard:
            self.sdcard.deinit()
        # depower SD card
        self._card_power.value = True
        card_cs = DigitalInOut(board.CARD_CS)
        card_cs.switch_to_output(False)
        # deinit display and SPI
        self.deinit_display()
        self._spi.deinit()
        sckpin = DigitalInOut(board.SCK)
        sckpin.switch_to_output(False)
        mosipin = DigitalInOut(board.MOSI)
        mosipin.switch_to_output(False)
        misopin = DigitalInOut(board.MISO)
        misopin.switch_to_output(False)

        time.sleep(0.05)

        sckpin.deinit()
        mosipin.deinit()
        misopin.deinit()
        self._spi = board.SPI()
        # power SD card
        self._card_power.value = False
        card_cs.deinit()
        print("sdcard init @", time.monotonic()-self.t)
        self.sdcard = sdcardio.SDCard(self._spi, board.CARD_CS, baudrate=20_000_000)
        vfs = storage.VfsFat(self.sdcard)
        print("mount vfs @", time.monotonic()-self.t)
        storage.mount(vfs, "/sd")
        self.init_display()
        self._image_counter = 0
        self._sd_label.text = "SD OK"
        self._sd_label.color = 0x00FF00
        

    def unmount_sd_card(self):
        try:
            storage.umount("/sd")
        except OSError:
            pass
        self._sd_label.text = "NO SD"
        self._sd_label.color = 0xFF0000


    def keys_debounce(self):
        # shutter button is true GPIO so we debounce as normal
        self.shutter.update()
        self.card_detect.update()
        self.up.update()
        self.down.update()
        self.left.update()
        self.right.update()
        self.select.update()
        self.ok.update()

    def tone(self, frequency, duration=0.1):
        with pwmio.PWMOut(
            board.SPEAKER, frequency=int(frequency), variable_frequency=False
            ) as pwm:
            self.mute.value = True
            pwm.duty_cycle = 0x8000
            time.sleep(duration)
            self.mute.value = False

    def live_preview_mode(self):
        self.camera.reconfigure(
            pixel_format=espcamera.PixelFormat.RGB565,
            frame_size=espcamera.FrameSize.HQVGA,
            )
        #self.effect = self._effect
        self.continuous_capture_start()

    def open_next_image(self, extension="jpg"):
        try:
            os.stat("/sd")
        except OSError:            # no SD card!
            raise RuntimeError("No SD card mounted")
        while True:
            filename = "/sd/img%04d.%s" % (self._image_counter, extension)
            self._image_counter += 1
            try:
                os.stat(filename)
            except OSError:
                break
        print("Writing to", filename)
        return open(filename, "wb")

    def capture_jpeg(self):
        try:
            os.stat("/sd")
        except OSError:            # no SD card!
            raise RuntimeError("No SD card mounted")
        
        self.camera.reconfigure(
            pixel_format=espcamera.PixelFormat.JPEG,
            frame_size=self.resolution_to_frame_size[self._resolution]
        )
        time.sleep(0.1)

        jpeg = self.camera.take(1)
        if jpeg is not None:
            print(f"Captured {len(jpeg)} bytes of jpeg data")
            print("Resolution %d x %d" % (self.camera.width, self.camera.height))

            with self.open_next_image() as f:
                chunksize = 16384
                for offset in range(0, len(jpeg), chunksize):
                    f.write(jpeg[offset:offset+chunksize])
                    print(end=".")
            print("# Wrote image")
        else:
            print("# frame capture failed")

    def continuous_capture_start(self):
        self._bitmap1 = self.camera.take(1)

    def capture_into_bitmap(self, bitmap):
        self._bitmap1 = self.camera.take(1)
        bitmaptools.blit(bitmap, self._bitmap1, 0, 0)

    def continuous_capture(self):
        return self.camera.take(1)

    def blit(self, bitmap):
        self._display_bus.send(42, struct.pack(">hh", 80,
                                               80 + bitmap.width - 1))
        self._display_bus.send(43, struct.pack(">hh", 32,
                                               32 + bitmap.height - 1))
        self._display_bus.send(44, bitmap)

    @property
    def led_level(self):
        return self._led_level

    @led_level.setter
    def led_level(self, new_level):
        level = (new_level + len(self.led_levels)) % len(self.led_levels)
        self._led_level = level
        self.pixels.brightness = self.led_levels[level]
        self.led_color = self.led_color

    @property
    def led_color(self):
        return self._led_color

    @led_color.setter
    def led_color(self, new_color):
        color = (new_color + len(self.colors)) % len(self.colors)
        self._led_color = color
        colors = self.colors[color]
        print("colors", colors)
        if isinstance(colors, int):
            self.pixels.fill(colors)
        else:
            self.pixels[:] = colors
