"""Protobuf encoding helpers and text normalization utilities."""

import base64
import unicodedata


def normalize(text):
    """Remove accents and lowercase for comparison."""
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.category(c).startswith('M')).lower()


# ---------------------------------------------------------------------------
# Protobuf encoding (for Google Flights tfs parameter)
# ---------------------------------------------------------------------------

def pb_varint(value):
    """Encode an integer as a protobuf varint."""
    result = bytearray()
    while value > 0x7f:
        result.append((value & 0x7f) | 0x80)
        value >>= 7
    result.append(value & 0x7f)
    return bytes(result)


def pb_tag(field, wire_type):
    """Encode a protobuf field tag."""
    return pb_varint((field << 3) | wire_type)


def pb_field_varint(field, value):
    return pb_tag(field, 0) + pb_varint(value)


def pb_field_bytes(field, data):
    return pb_tag(field, 2) + pb_varint(len(data)) + data


def pb_field_string(field, s):
    return pb_field_bytes(field, s.encode("utf-8"))


def build_explore_tfs(origin_geo, dest_geo, dep_date, ret_date, cabin="economy"):
    """Build the tfs protobuf parameter for Google Flights Explore URL."""
    cabin_val = 1 if cabin == "economy" else 3

    origin_sub = pb_field_varint(1, 2) + pb_field_string(2, origin_geo)
    dep_leg = pb_field_string(2, dep_date) + pb_field_bytes(13, origin_sub)
    ret_leg = pb_field_string(2, ret_date) + pb_field_bytes(14, origin_sub)
    dest_sub = pb_field_string(2, dest_geo)
    filter_sub = bytes([0x08]) + bytes([0xff] * 9) + bytes([0x01])

    tfs = (
        pb_field_varint(1, 28)
        + pb_field_varint(2, 3)
        + pb_field_bytes(3, dep_leg)
        + pb_field_bytes(3, ret_leg)
        + pb_field_varint(8, 1)
        + pb_field_varint(9, cabin_val)
        + pb_field_varint(14, 1)
        + pb_field_bytes(16, filter_sub)
        + pb_field_varint(19, 1)
        + pb_field_bytes(22, dest_sub)
    )
    return base64.urlsafe_b64encode(tfs).rstrip(b"=").decode()


def build_explore_url(origin_geo, dest_geo, dep_date, ret_date, cabin="economy"):
    """Build a complete Google Flights Explore URL with cabin class."""
    tfs = build_explore_tfs(origin_geo, dest_geo, dep_date, ret_date, cabin)
    return f"https://www.google.com/travel/explore?tfs={tfs}&tfu=GgA&hl=es&curr=EUR"


def build_google_url(origin, destination, dep_date, ret_date, cabin="economy"):
    """Build a direct Google Flights search URL."""
    tt = "1" if cabin == "economy" else "3"
    return (
        f"https://www.google.com/travel/flights#flt="
        f"{origin}.{destination}.{dep_date}*{destination}.{origin}.{ret_date}"
        f";c:EUR;e:{tt};s:1;sd:1;t:f"
    )
