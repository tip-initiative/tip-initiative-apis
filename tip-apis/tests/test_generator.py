from generator import clean_description


def test_clean_description():
    in_ = "Contact Last  Name   ( not necessary  )"
    want = "Contact Last Name (not necessary)"
    assert want == clean_description(in_)


def test_clean_description_maintain_newlines():
    in_ = """
A common object defining the Pricing metric 
CPM - Cost-per-thousand,
   CPP - Cost-per-point,
CPE   - Cost-per-engagement,
CPA -     Cost-per-action
"""
    want = """A common object defining the Pricing metric
CPM - Cost-per-thousand,
CPP - Cost-per-point,
CPE - Cost-per-engagement,
CPA - Cost-per-action"""
    r = clean_description(in_)
    assert r == want
