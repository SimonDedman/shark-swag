import intake_classify as ic


def g(title, note="", url="https://example.com/products/thing"):
    return ic.classify(title, note, url)


def test_a_book_goes_to_section_three_even_when_it_mentions_gear():
    r = g("Snorkelling with Sharks: a picture book for young readers")
    assert r.section == "3"
    assert "book" in r.keyword


def test_an_ngo_host_wins_over_the_product_words():
    r = g("Organic cotton tee", url="https://www.sharktrustclothing.com/products/tee")
    assert r.section == "6"
    assert r.keyword.startswith("host:")


def test_equipment_keywords():
    assert g("Junior mask and snorkel set").section == "4"


def test_arts_keywords():
    assert g("Shark sticker sheet and colouring pencils").section == "5"


def test_toy_keywords():
    assert g("Great white plush soft toy").section == "2"


def test_clothing_keywords():
    assert g("Hammerhead hoodie").section == "1"


def test_wildcard_keywords():
    assert g("Adopt a basking shark, annual subscription").section == "7"


def test_an_unmatched_title_leaves_everything_blank():
    """No rule firing must read as 'nobody has classified this', not as a
    silent default into whichever section happens to be first."""
    r = g("A thing")
    assert r.section == ""
    assert r.sub == ""
    assert r.keyword == ""


def test_age_bands():
    assert g("Shark bodysuit for newborns").age == "Baby & Toddler"
    assert g("Kids shark tee").age == "Kids"
    assert g("Youth shark hoodie").age == "Youth"
    assert g("Shark tee").age == "Adult"


def test_baby_clothing_lands_in_a_subsection_that_exists():
    r = g("Lemon shark organic cotton onesie")
    assert r.section == "1"
    assert r.sub == "Baby & Toddler"
    assert r.sub in ic.valid_subs("1")


def test_an_age_with_no_matching_subsection_leaves_the_subsection_blank():
    """Section 2 has no Adult band. Guessing one would put the entry in a
    heading that does not exist in the document."""
    r = g("Shark chess set")
    assert r.section == "2"
    assert r.age == "Adult"
    assert r.sub == ""


def test_section_four_uses_kind_not_age():
    r = g("Junior rash guard, UPF 50")
    assert r.section == "4"
    assert r.sub == "Rash guards, wetsuits & swim gear"


def test_section_seven_subsections():
    assert g("Shark advent calendar").sub == "Advent calendars & seasonal"
    assert g("Adopt a shark for a year").sub == "Adoptions & subscriptions"
    assert g("Cage diving experience day").sub == "Experiences"


def test_ngo_hosts_are_derived_from_the_data_not_hardcoded():
    hosts = ic.ngo_hosts()
    assert "sharktrust.org" in " ".join(hosts)
    for host, sub in hosts.items():
        assert sub in ic.valid_subs("6")


def test_the_note_is_searched_as_well_as_the_title():
    r = g("Untitled listing", note="it is a lovely plush toy")
    assert r.section == "2"
