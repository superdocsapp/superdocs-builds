"""THE safety guarantee: shared-block edits propagate everywhere,
but property-specific overrides are never clobbered."""

import copy
import unittest

from strgen.assembly import deep_merge_copy, resolve
from strgen.models import I18N_KEY, Property, SharedBlock


def make_block(content):
    return SharedBlock(id="wifi-shared", kind="wifi", name="Standard WiFi",
                       content=copy.deepcopy(content))


def make_property(links=None, overrides=None):
    p = Property(id="casa-test", name="Casa Test")
    for k, v in (links or {}).items():
        p.link_block(k, v)
    for k, v in (overrides or {}).items():
        p.set_override(k, v)
    return p


WIFI_CONTENT = {
    "ssid": "CasaNet", "password": "oldpass",
    "instructions": {I18N_KEY: {"en": "Open settings and join the network.",
                                "es": "Abre ajustes y únete a la red."}},
}


class SharedBlockPropagation(unittest.TestCase):
    def test_edit_propagates_to_every_linked_property(self):
        block = make_block(WIFI_CONTENT)
        blocks = {"wifi-shared": block}
        casa = make_property(links={"wifi": "wifi-shared"})
        loft = make_property(links={"wifi": "wifi-shared"})

        # Operator edits the SHARED block once...
        block.content["password"] = "newpass"
        block.content["instructions"][I18N_KEY]["fr"] = "Ouvrez les réglages."

        # ...and both properties see it immediately.
        for prop in (casa, loft):
            resolved = resolve("wifi", prop, blocks)
            self.assertEqual(resolved["password"], "newpass")
            self.assertEqual(resolved["instructions"][I18N_KEY]["fr"],
                             "Ouvrez les réglages.")

    def test_unrelated_properties_untouched(self):
        block = make_block(WIFI_CONTENT)
        blocks = {"wifi-shared": block}
        linked = make_property(links={"wifi": "wifi-shared"})
        solo = make_property(overrides={"wifi": {"ssid": "SoloNet"}})

        block.content["password"] = "changed"
        self.assertEqual(resolve("wifi", linked, blocks)["password"], "changed")
        self.assertEqual(resolve("wifi", solo, blocks)["ssid"], "SoloNet")
        self.assertNotIn("password", resolve("wifi", solo, blocks))


class OverrideSafety(unittest.TestCase):
    """Property-specific text must NEVER be overwritten by block edits."""

    def setUp(self):
        self.block = make_block(WIFI_CONTENT)
        self.blocks = {"wifi-shared": self.block}

    def test_override_wins_at_render_time(self):
        prop = make_property(
            links={"wifi": "wifi-shared"},
            overrides={"wifi": {"password": "MY-SECRET"}},
        )
        resolved = resolve("wifi", prop, self.blocks)
        self.assertEqual(resolved["password"], "MY-SECRET")
        # non-overridden siblings still come from the block
        self.assertEqual(resolved["ssid"], "CasaNet")

    def test_override_survives_repeated_block_edits(self):
        prop = make_property(
            links={"wifi": "wifi-shared"},
            overrides={"wifi": {"password": "MY-SECRET"}},
        )
        for generation in range(1, 6):
            self.block.content["password"] = f"gen-{generation}"
            self.block.content["instructions"][I18N_KEY]["en"] = f"instructions gen {generation}"
            resolved = resolve("wifi", prop, self.blocks)
            self.assertEqual(resolved["password"], "MY-SECRET",
                             "block edit leaked into property override!")
            self.assertEqual(resolved["instructions"][I18N_KEY]["en"],
                             f"instructions gen {generation}")

    def test_property_namespace_never_mutated_by_block_writes(self):
        prop = make_property(
            links={"wifi": "wifi-shared"},
            overrides={"wifi": {"password": "MY-SECRET",
                                "note": {I18N_KEY: {"en": "Ask Ana for the guest network"}}}},
        )
        overrides_snapshot = copy.deepcopy(prop.overrides)

        # Simulate a bulk "rebrand all properties" job that edits blocks only.
        self.block.content = {"ssid": "NewNet", "password": "bulk",
                              "instructions": {I18N_KEY: {"en": "x"}}, "portal": True}

        self.assertEqual(prop.overrides, overrides_snapshot,
                         "property override namespace was mutated by block edit")

    def test_i18n_partial_translation_merges_per_language(self):
        prop = make_property(
            links={"wifi": "wifi-shared"},
            overrides={"wifi": {"instructions": {I18N_KEY: {"es": "Texto propio."}}}},
        )
        self.block.content["instructions"][I18N_KEY]["en"] = "Shared EN text."
        resolved = resolve("wifi", prop, self.blocks)
        self.assertEqual(resolved["instructions"][I18N_KEY]["en"], "Shared EN text.")
        self.assertEqual(resolved["instructions"][I18N_KEY]["es"], "Texto propio.")

    def test_lists_replace_predictably(self):
        rules = SharedBlock(id="rules-shared", kind="rules", name="Rules",
                            content={"rules": ["Be quiet", "No smoking"],
                                     "quiet_hours": "22:00-08:00"})
        blocks = {"rules-shared": rules}
        prop = make_property(links={"rules": "rules-shared"})
        prop.set_override("rules", {"rules": ["Pet-friendly house"]})

        resolved = resolve("rules", prop, blocks)
        self.assertEqual(resolved["rules"], ["Pet-friendly house"])
        self.assertEqual(resolved["quiet_hours"], "22:00-08:00")  # inherited

    def test_resolve_returns_copies_not_references(self):
        prop = make_property(links={"wifi": "wifi-shared"})
        once = resolve("wifi", prop, self.blocks)
        once["password"] = "tampered"
        twice = resolve("wifi", prop, self.blocks)
        self.assertEqual(twice["password"], "oldpass")

    def test_missing_link_fails_loudly(self):
        from strgen.errors import MissingLink
        prop = make_property(links={"wifi": "ghost-id"})
        with self.assertRaises(MissingLink):
            resolve("wifi", prop, self.blocks)


class MergeSemantics(unittest.TestCase):
    def test_deep_merge_copy_is_pure(self):
        base = {"a": {"b": 1}, "list": [1, 2]}
        override = {"a": {"c": 2}, "list": [3]}
        merged = deep_merge_copy(base, override)
        self.assertEqual(base, {"a": {"b": 1}, "list": [1, 2]})
        self.assertEqual(merged, {"a": {"b": 1, "c": 2}, "list": [3]})


if __name__ == "__main__":
    unittest.main()
