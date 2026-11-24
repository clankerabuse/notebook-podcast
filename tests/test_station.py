"""Tests for station.py, the RSS feed builder. Stdlib only, no network, no ffmpeg.

Run: /usr/bin/python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import station  # noqa: E402

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
BASE = "http://example.invalid:8765"


def write_episode(ep_dir, slug, title, text="Opening sentence. Second one.",
                  mp3_bytes=b"not really audio", mp3=True):
    os.makedirs(ep_dir, exist_ok=True)
    spec = {"title": title, "host": {"voice": "v"},
            "paragraphs": [{"text": text}]}
    with open(os.path.join(ep_dir, slug + ".json"), "w", encoding="utf-8") as f:
        json.dump(spec, f)
    if mp3:
        with open(os.path.join(ep_dir, slug + ".mp3"), "wb") as f:
            f.write(mp3_bytes)
    return os.path.join(ep_dir, slug + ".mp3")


class StationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.ep = os.path.join(self.root, "episodes")
        self.notes = os.path.join(self.root, "notes")
        self.out = os.path.join(self.root, "feed.xml")

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, durations, **kw):
        """Build a feed with ffprobe stubbed out, keyed by mp3 basename."""
        def fake_probe(path):
            return durations[os.path.basename(path)]
        with mock.patch.object(station, "probe_duration", fake_probe):
            return station.build(episodes_dir=self.ep, notes_dir=self.notes,
                                 out=self.out, base_url=BASE, **kw)

    def test_feed_is_valid_and_lists_the_episode(self):
        mp3 = write_episode(self.ep, "one-light-day", "One Light-Day")
        sizes = os.path.getsize(mp3)
        self.build({"one-light-day.mp3": 643.336})

        tree = ET.parse(self.out)
        channel = tree.getroot().find("channel")
        self.assertEqual(tree.getroot().tag, "rss")
        self.assertEqual(tree.getroot().get("version"), "2.0")
        self.assertEqual(channel.findtext("title"), station.DEFAULT_TITLE)

        items = channel.findall("item")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.findtext("title"), "One Light-Day")
        self.assertEqual(item.findtext(ITUNES + "duration"), "10:43")
        guid = item.find("guid")
        self.assertIsNotNone(guid)
        self.assertEqual(guid.text, "one-light-day")
        self.assertEqual(guid.get("isPermaLink"), "false")
        enc = item.find("enclosure")
        self.assertIsNotNone(enc)
        self.assertEqual(enc.get("url"), BASE + "/episodes/one-light-day.mp3")
        self.assertEqual(enc.get("type"), "audio/mpeg")
        self.assertEqual(int(enc.get("length")), sizes)
        self.assertTrue(item.findtext("pubDate"))

    def test_notes_sources_become_the_description(self):
        write_episode(self.ep, "ep-a", "Ep A")
        os.makedirs(self.notes, exist_ok=True)
        with open(os.path.join(self.notes, "ep-a.md"), "w", encoding="utf-8") as f:
            f.write("# Sources\n\n"
                    "- https://example.invalid/paper\n"
                    "- https://example.invalid/other).\n\n"
                    "# Facts\n\nA fact with https://example.invalid/ignored\n")
        self.build({"ep-a.mp3": 60.0})

        desc = ET.parse(self.out).getroot().find("channel/item/description").text
        self.assertIn("https://example.invalid/paper", desc)
        self.assertIn("https://example.invalid/other", desc)
        self.assertNotIn("ignored", desc)
        self.assertNotIn("A fact", desc)

    def test_missing_notes_falls_back_to_one_sentence(self):
        write_episode(self.ep, "ep-b", "Ep B", text="First sentence here. Then more.")
        self.build({"ep-b.mp3": 60.0})

        desc = ET.parse(self.out).getroot().find("channel/item/description").text
        self.assertEqual(desc, "First sentence here.")

    def test_notes_without_a_sources_heading_uses_the_top_urls(self):
        write_episode(self.ep, "ep-c", "Ep C")
        os.makedirs(self.notes, exist_ok=True)
        with open(os.path.join(self.notes, "ep-c.md"), "w", encoding="utf-8") as f:
            f.write("Grounding: https://example.invalid/top\n\n# Facts\n\nbody\n")
        self.build({"ep-c.mp3": 60.0})

        desc = ET.parse(self.out).getroot().find("channel/item/description").text
        self.assertIn("https://example.invalid/top", desc)

    def test_markup_in_a_title_survives_the_round_trip(self):
        write_episode(self.ep, "ep-d", "Mars & Venus: <the> long way")
        self.build({"ep-d.mp3": 60.0})

        title = ET.parse(self.out).getroot().findtext("channel/item/title")
        self.assertEqual(title, "Mars & Venus: <the> long way")

    def test_episode_without_an_mp3_is_skipped_not_fatal(self):
        write_episode(self.ep, "half-done", "Half Done", mp3=False)
        write_episode(self.ep, "real", "Real")
        xml_bytes, items, skipped = self.build({"real.mp3": 61.0})

        self.assertEqual(items, ["real"])
        self.assertEqual(skipped, ["half-done"])
        self.assertEqual(len(ET.fromstring(xml_bytes).findall("channel/item")), 1)

    def test_unprobeable_mp3_is_skipped_not_fatal(self):
        write_episode(self.ep, "broken", "Broken")
        def boom(path):
            raise RuntimeError("ffprobe failed")
        with mock.patch.object(station, "probe_duration", boom):
            xml_bytes, items, skipped = station.build(
                episodes_dir=self.ep, notes_dir=self.notes, out=self.out, base_url=BASE)
        self.assertEqual(items, [])
        self.assertEqual(skipped, ["broken"])
        self.assertEqual(ET.fromstring(xml_bytes).findall("channel/item"), [])

    def test_newest_episode_first_and_limit(self):
        for slug, stamp in (("old", 1_600_000_000), ("new", 1_700_000_000)):
            mp3 = write_episode(self.ep, slug, slug.upper())
            os.utime(mp3, (stamp, stamp))
        self.build({"old.mp3": 60.0, "new.mp3": 60.0})

        titles = [i.findtext("title") for i in
                  ET.parse(self.out).getroot().findall("channel/item")]
        self.assertEqual(titles, ["NEW", "OLD"])

        self.build({"old.mp3": 60.0, "new.mp3": 60.0}, limit=1)
        titles = [i.findtext("title") for i in
                  ET.parse(self.out).getroot().findall("channel/item")]
        self.assertEqual(titles, ["NEW"])

    def test_guid_survives_a_base_url_change(self):
        write_episode(self.ep, "stable", "Stable")
        self.build({"stable.mp3": 60.0})
        first = ET.parse(self.out).getroot().findtext("channel/item/guid")
        with mock.patch.object(station, "probe_duration", lambda p: 60.0):
            station.build(episodes_dir=self.ep, notes_dir=self.notes, out=self.out,
                          base_url="http://10.0.0.2:9000")
        second = ET.parse(self.out).getroot().findtext("channel/item/guid")
        self.assertEqual(first, second)

    def test_empty_episodes_directory_builds_an_empty_feed(self):
        os.makedirs(self.ep)
        xml_bytes, items, skipped = self.build({})
        self.assertEqual((items, skipped), ([], []))
        self.assertEqual(ET.fromstring(xml_bytes).findall("channel/item"), [])

    def test_durations(self):
        self.assertEqual(station.hhmmss(643.336), "10:43")
        self.assertEqual(station.hhmmss(59), "0:59")
        self.assertEqual(station.hhmmss(3600), "1:00:00")
        self.assertEqual(station.hhmmss(3725.4), "1:02:05")


if __name__ == "__main__":
    unittest.main()
