
# References to actually implement processing of keyscan codes in the future
# https://techdocs.altium.com/display/FPGA/PS2+Keyboard+Scan+Codes
# https://www.win.tue.nl/~aeb/linux/kbd/scancodes-1.html
# https://www.nutsvolts.com/magazine/article/get-ascii-data-from-ps-2-keyboards


def keyscan_to_utf8(captured_raw):
    raise Exception('Not yet implemented')


def keyscan_to_hex(captured_raw):
    ret_str = ''
    for byte in captured_raw:
        ret_str += '{:0x} '.format(byte)
    processed_len = len(captured_raw)
    return ret_str, processed_len


def keyscan_no_convert(captured_raw):
    ret_str = captured_raw
    processed_len = len(captured_raw)
    return ret_str, processed_len


def utf8_no_convert(inject_str):
    return inject_str


def utf8_to_keyscan(inject_str):
    raise Exception('Not yet implemented')
