from generator import clean_description


def test_clean_description():
    in_ = "Contact Last  Name   ( not necessary  )"
    want = "Contact Last Name (not necessary)"
    assert want == clean_description(in_)
