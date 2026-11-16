"""Regression tests for MPEG-PS boundaries and the three supplied movies."""
import importlib.util
import struct
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parent / "提取并合成.py"
spec = importlib.util.spec_from_file_location("pss_decoder", MODULE)
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


def packet(stream_id, payload):
    return b"\x00\x00\x01" + bytes([stream_id]) + struct.pack(">H", len(payload)) + payload


class PacketTests(unittest.TestCase):
    def test_embedded_audio_marker_is_not_a_packet(self):
        fake_header_inside_video = b"video\x00\x00\x01\xbd\x00\x10not a packet"
        encoded = packet(0xE0, fake_header_inside_video) + packet(0xBD, b"real audio") + b"\x00\x00\x01\xb9"
        items = list(decoder.ps_packets(encoded))
        self.assertEqual([item[0] for item in items], [0xE0, 0xBD, 0xB9])
        self.assertEqual(items[1][2], b"real audio")

    def test_truncated_packet_is_rejected(self):
        with self.assertRaises(ValueError):
            list(decoder.ps_packets(b"\x00\x00\x01\xbd\x00\x10too short"))

    def test_three_real_movie_structures(self):
        counts = {"MV_LG01": (144, 583680), "MV_OP01": (4505, 18329600),
                  "MV_END01": (4514, 18368512)}
        if not all((decoder.DEFAULT_INPUT / (name + ".PSS")).exists() for name in counts):
            self.skipTest("Original PSS movie samples are unavailable")
        for name, (packets, length) in counts.items():
            with self.subTest(name=name):
                pcm, info = decoder.decode_pss((decoder.DEFAULT_INPUT / (name + ".PSS")).read_bytes())
                self.assertEqual(info["audio_packets"], packets)
                self.assertEqual(info["ssbd_bytes"], length)
                self.assertEqual(pcm.size * 2, length)
                self.assertLess(info["max_packet_pts_drift_ticks"], 1)
                self.assertEqual(info["first_audio_pts_90khz"], info["first_video_pts_90khz"])


if __name__ == "__main__":
    unittest.main()
