from soc2_index.catalog import load_catalog, load_sample_catalog

FULL_IDS = {
    "CC1.1", "CC1.2", "CC1.3", "CC1.4", "CC1.5",
    "CC2.1", "CC2.2", "CC2.3",
    "CC3.1", "CC3.2", "CC3.3", "CC3.4",
    "CC4.1", "CC4.2",
    "CC5.1", "CC5.2", "CC5.3",
    "CC6.1", "CC6.2", "CC6.3", "CC6.4", "CC6.5", "CC6.6", "CC6.7", "CC6.8",
    "CC7.1", "CC7.2", "CC7.3", "CC7.4", "CC7.5",
    "CC8.1",
    "CC9.1", "CC9.2",
}

SAMPLE_IDS = {
    "CC6.1", "CC6.2", "CC6.3", "CC6.4", "CC6.5", "CC6.6", "CC6.7", "CC6.8",
    "CC7.1", "CC7.2", "CC7.3", "CC7.4", "CC7.5",
}


def test_full_catalog_33():
    cat = load_catalog()
    assert len(cat.ids) == 33
    assert set(cat.ids) == FULL_IDS


def test_sample_catalog_13_subset():
    cat = load_sample_catalog()
    assert len(cat.ids) == 13
    assert set(cat.ids) == SAMPLE_IDS
    assert SAMPLE_IDS <= FULL_IDS
